from datetime import date
import logging

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from digitmileapi.models import (
    ReplayArchive,
    Run,
    SpecialTileTrigger,
    TurnEvent,
    WeeklyCompactionRun,
)
from digitmileapi.replay_archives import (
    ensure_archive_root,
    verify_replay_archive,
    write_replay_archive,
)
from digitmileapi.run_bucket_trends import rebuild_historical_run_bucket_trends
from digitmileapi.weekly_aggregation import aggregate_weekly_rollups
from digitmileapi.weekly_rollups import week_end_for, week_start_for


logger = logging.getLogger(__name__)


def _log_compaction_event(event, **context):
    logger.info("%s %s", event, context)


class Command(BaseCommand):
    help = "Aggregate, archive, verify, and compact one closed gameplay week"

    def add_arguments(self, parser):
        parser.add_argument("week_start", help="Week start date in YYYY-MM-DD format")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Build aggregate counts and archive plan without deleting raw rows",
        )
        parser.add_argument(
            "--overwrite-archives",
            action="store_true",
            help="Rewrite existing READY archives during compaction",
        )
        parser.add_argument(
            "--clear-game-map",
            action="store_true",
            help="Clear Run.game_map after archive verification succeeds",
        )

    def handle(self, *args, **options):
        try:
            requested_week_start = date.fromisoformat(options["week_start"])
        except ValueError as exc:
            raise CommandError("week_start must be YYYY-MM-DD") from exc

        week_start = week_start_for(requested_week_start)
        week_end = week_end_for(week_start)
        _log_compaction_event(
            "weekly_compaction_start",
            week_start=str(week_start),
            week_end=str(week_end),
            dry_run=options["dry_run"],
            overwrite_archives=options["overwrite_archives"],
            clear_game_map=options["clear_game_map"],
        )
        compaction, _ = WeeklyCompactionRun.objects.get_or_create(
            week_start=week_start,
            defaults={"week_end": week_end},
        )
        previous_status = compaction.status
        if (
            previous_status == WeeklyCompactionRun.Status.COMPACTED
            and not options["dry_run"]
        ):
            self.stdout.write(self.style.WARNING("Week is already compacted"))
            return

        compaction.week_end = week_end
        compaction.started_at = timezone.now()
        compaction.status = WeeklyCompactionRun.Status.PENDING
        compaction.notes = ""
        compaction.save()

        # Stream over runs rather than materialise list(runs). At national
        # medium adoption a single week is ~140k Run rows whose game_map
        # JSONField alone would consume hundreds of MB if loaded eagerly,
        # tipping the 3.8 GiB host into OOM during the archive-write loop.
        # Iterator + per-iteration build of run_ids/student_level_pairs
        # holds chunk_size rows at a time instead.
        runs_qs = (
            Run.objects.filter(
                created_at__date__gte=week_start, created_at__date__lte=week_end
            )
            .select_related("student__classroom")
            .order_by("created_at", "id")
        )

        run_count_total = runs_qs.count()
        if run_count_total == 0:
            compaction.notes = "No runs found for requested week"
            compaction.completed_at = timezone.now()
            compaction.save(update_fields=["notes", "completed_at", "updated_at"])
            self.stdout.write(
                self.style.WARNING("No runs found for the requested week")
            )
            return

        ensure_archive_root()
        rollup_result = aggregate_weekly_rollups(week_start)
        _log_compaction_event(
            "weekly_compaction_aggregation_result",
            week_start=str(week_start),
            result=rollup_result,
        )
        compaction.status = WeeklyCompactionRun.Status.AGGREGATED
        compaction.run_count = run_count_total
        # Use a date-range subquery filter instead of run__in=<list>. PG can
        # plan this efficiently with the existing created_at index; no Python
        # materialisation of run IDs needed for counts.
        runs_in_week = Run.objects.filter(
            created_at__date__gte=week_start, created_at__date__lte=week_end
        )
        compaction.turn_count = TurnEvent.objects.filter(
            run__in=runs_in_week
        ).count()
        compaction.trigger_count = SpecialTileTrigger.objects.filter(
            turn__run__in=runs_in_week
        ).count()
        compaction.save()

        archive_bytes_written = 0
        archive_runs_written = 0
        archive_runs_verified = 0
        student_level_pairs = set()
        run_ids = []

        for run in runs_qs.iterator(chunk_size=500):
            run_ids.append(run.id)
            student_level_pairs.add((run.student_id, run.level))

            existing_archive = getattr(run, "replay_archive", None)
            if (
                existing_archive
                and existing_archive.archive_status == ReplayArchive.ArchiveStatus.READY
                and existing_archive.storage_path
                and not options["overwrite_archives"]
            ):
                archive = existing_archive
            else:
                archive = write_replay_archive(run)
                archive_runs_written += 1
                archive_bytes_written += archive.compressed_size_bytes or 0
                _log_compaction_event(
                    "weekly_compaction_archive_write_result",
                    week_start=str(week_start),
                    run_id=run.id,
                    storage_path=archive.storage_path,
                    checksum_sha256=archive.checksum_sha256,
                    compressed_size_bytes=archive.compressed_size_bytes,
                )

            archive_is_valid = verify_replay_archive(archive)
            _log_compaction_event(
                "weekly_compaction_archive_verification_result",
                week_start=str(week_start),
                run_id=run.id,
                verified=archive_is_valid,
                archive_status=archive.archive_status,
                verification_error=archive.verification_error,
            )
            if archive_is_valid:
                archive_runs_verified += 1
            else:
                compaction.status = WeeklyCompactionRun.Status.FAILED
                compaction.notes = f"Archive verification failed for run {run.id}"
                compaction.completed_at = timezone.now()
                compaction.archive_runs_written = archive_runs_written
                compaction.archive_runs_verified = archive_runs_verified
                compaction.archive_bytes_written = archive_bytes_written
                compaction.save()
                raise CommandError(compaction.notes)

        compaction.status = WeeklyCompactionRun.Status.VERIFIED
        compaction.archive_runs_written = archive_runs_written
        compaction.archive_runs_verified = archive_runs_verified
        compaction.archive_bytes_written = archive_bytes_written
        compaction.save()

        run_bucket_result = rebuild_historical_run_bucket_trends(
            student_level_pairs,
            include_run_ids=run_ids,
        )
        _log_compaction_event(
            "weekly_compaction_run_bucket_result",
            week_start=str(week_start),
            result=run_bucket_result,
        )

        call_command(
            "verify_weekly_rollups",
            week_start.isoformat(),
            "--require-archives",
            "--verify-run-buckets",
        )

        if options["dry_run"]:
            compaction.notes = f"Dry run complete. rollups={rollup_result}, verified_archives={archive_runs_verified}"
            compaction.completed_at = timezone.now()
            compaction.save(update_fields=["notes", "completed_at", "updated_at"])
            self.stdout.write(self.style.SUCCESS(compaction.notes))
            return

        with transaction.atomic():
            # Use the date-range subquery filter again here so we don't pass
            # 140k IDs to PG in a single IN clause. The created_at index
            # makes this efficient.
            trigger_rows_deleted, _ = SpecialTileTrigger.objects.filter(
                turn__run__in=runs_in_week
            ).delete()
            turn_rows_deleted, _ = TurnEvent.objects.filter(
                run__in=runs_in_week
            ).delete()

            update_values = {"raw_data_compacted_at": timezone.now()}
            if options["clear_game_map"]:
                update_values["game_map"] = []
            runs_in_week.update(**update_values)

        _log_compaction_event(
            "weekly_compaction_delete_result",
            week_start=str(week_start),
            trigger_rows_deleted=trigger_rows_deleted,
            turn_rows_deleted=turn_rows_deleted,
            cleared_game_map=options["clear_game_map"],
        )

        compaction.status = WeeklyCompactionRun.Status.COMPACTED
        compaction.turn_rows_deleted = turn_rows_deleted
        compaction.trigger_rows_deleted = trigger_rows_deleted
        compaction.completed_at = timezone.now()
        compaction.notes = f"Compaction complete for {week_start} through {week_end}"
        compaction.save()

        # delete_pattern is a django-redis extension; skip when the cache
        # backend doesn't provide it (e.g. DummyCache under the benchmark
        # dummy-cache overlay, where there is nothing to invalidate).
        if hasattr(cache, "delete_pattern"):
            cache.delete_pattern("teacher_stats_viz:*")
            cache.delete_pattern("teacher_dashboard:*")

        self.stdout.write(
            self.style.SUCCESS(
                f"Compaction complete: runs={run_count_total}, archives_verified={archive_runs_verified}, turns_deleted={turn_rows_deleted}, triggers_deleted={trigger_rows_deleted}"
            )
        )
