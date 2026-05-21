from datetime import date
import json
import logging
import os
import subprocess
import sys

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


SLICE_RESULT_SENTINEL = "__COMPACTION_SLICE_RESULT__"

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
        parser.add_argument(
            "--teacher-id",
            type=str,
            default=None,
            help=(
                "Compact only the slice of the week belonging to one teacher. "
                "Skips verify_weekly_rollups and final week-level status "
                "updates — caller is responsible for orchestration."
            ),
        )
        parser.add_argument(
            "--per-teacher",
            action="store_true",
            help=(
                "Discover all teachers with runs in this week and compact each "
                "teacher's slice sequentially. Bounds Python heap and PG "
                "bulk-insert pressure per slice to ~hundreds of MB even at "
                "national-medium scale. verify_weekly_rollups runs once after "
                "all slices complete."
            ),
        )
        parser.add_argument(
            "--skip-verification",
            action="store_true",
            help=(
                "Skip the verify_weekly_rollups call after compaction. "
                "Use when the operator runs verification out-of-band."
            ),
        )
        parser.add_argument(
            "--max-workers",
            type=int,
            default=1,
            help=(
                "Max concurrent per-teacher worker subprocesses when "
                "--per-teacher is in use. Default 1 = sequential. Each worker "
                "spawns its own `manage.py compact_weekly_runs --teacher-id N "
                "--skip-verification --emit-json-result` subprocess so its "
                "Python heap and PG connection are isolated from the others. "
                "Cap to ~3-4 in production to avoid exhausting the PG "
                "connection pool against Gunicorn workers + flusher."
            ),
        )
        parser.add_argument(
            "--emit-json-result",
            action="store_true",
            help=(
                "Used by the parallel per-teacher orchestrator. Requires "
                "--teacher-id. Emits a single sentinel-prefixed JSON line "
                "with the slice_result dict so the parent can aggregate."
            ),
        )

    def handle(self, *args, **options):
        if options["per_teacher"] and options["teacher_id"] is not None:
            raise CommandError(
                "--per-teacher and --teacher-id are mutually exclusive"
            )
        if options["emit_json_result"] and options["teacher_id"] is None:
            raise CommandError(
                "--emit-json-result requires --teacher-id (it is the "
                "worker-mode flag for the parallel per-teacher orchestrator)"
            )
        if options["max_workers"] < 1:
            raise CommandError("--max-workers must be >= 1")
        if options["max_workers"] > 1 and not options["per_teacher"]:
            raise CommandError(
                "--max-workers > 1 requires --per-teacher (parallelism is "
                "only meaningful across teacher slices)"
            )

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
            teacher_id=options["teacher_id"],
            per_teacher=options["per_teacher"],
        )

        ensure_archive_root()

        if options["per_teacher"]:
            self._handle_per_teacher(week_start, week_end, options)
            return

        # Single-slice mode: either whole-week (teacher_id=None) or one
        # teacher's slice. We only own the week-level WeeklyCompactionRun
        # row when teacher_id is None — for an explicit --teacher-id call
        # the caller is orchestrating the week and we leave bookkeeping
        # to them.
        compaction = None
        if options["teacher_id"] is None:
            compaction = self._open_week_compaction_record(week_start, week_end)
            if compaction is None:  # Already COMPACTED
                return

        slice_result = self._compact_slice(
            week_start,
            week_end,
            teacher_id=options["teacher_id"],
            options=options,
            week_record=compaction,
        )

        # verify_weekly_rollups is now invoked INSIDE _compact_slice before
        # the raw-row delete (otherwise raw counts come back zero and every
        # rollup field looks like a mismatch). Nothing to do here.

        if compaction is not None:
            self._finalize_week_record(
                compaction, [slice_result], week_start, week_end, options
            )

        if options["teacher_id"] is None:
            self._invalidate_dashboard_cache()

        if options["emit_json_result"]:
            # Sentinel-prefixed single line for the parallel orchestrator to
            # parse out of captured stdout. Emitted before the human summary
            # so it survives even if the summary write is truncated.
            self.stdout.write(
                f"{SLICE_RESULT_SENTINEL} {json.dumps(slice_result)}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                self._format_summary(slice_result, scope=(
                    f"teacher={options['teacher_id']}"
                    if options["teacher_id"] is not None
                    else "week"
                ))
            )
        )

    # --------------------------------------------------------------
    # Per-teacher orchestrator
    # --------------------------------------------------------------

    def _handle_per_teacher(self, week_start, week_end, options):
        teacher_ids = list(
            Run.objects.filter(
                created_at__date__gte=week_start,
                created_at__date__lte=week_end,
            )
            .values_list("student__classroom__teacher_id", flat=True)
            .distinct()
            .order_by("student__classroom__teacher_id")
        )

        if not teacher_ids:
            self.stdout.write(
                self.style.WARNING("No runs found for the requested week")
            )
            return

        compaction = self._open_week_compaction_record(week_start, week_end)
        if compaction is None:  # Already COMPACTED
            return

        max_workers = max(1, int(options["max_workers"]))
        # Don't spawn more workers than slices — saves bookkeeping noise.
        effective_workers = min(max_workers, len(teacher_ids))

        self.stdout.write(
            f"Per-teacher compaction: {len(teacher_ids)} teachers, "
            f"workers={effective_workers}"
        )

        if effective_workers == 1:
            slice_results = self._run_slices_sequential(
                teacher_ids, week_start, week_end, options, compaction
            )
        else:
            slice_results = self._run_slices_parallel(
                teacher_ids, week_start, effective_workers, options
            )

        # Per-slice verification (now inside _compact_slice) runs before each
        # teacher's raw rows are deleted, scoped to that teacher's data via
        # verify_weekly_rollups --teacher-id. The whole-week assembly is
        # implicitly correct iff each per-teacher slice verified; running a
        # post-delete whole-week verify here would just see raw=0 because
        # every slice has already deleted its turns/triggers.

        self._finalize_week_record(
            compaction, slice_results, week_start, week_end, options
        )
        self._invalidate_dashboard_cache()

        totals = self._sum_slice_results(slice_results)
        self.stdout.write(
            self.style.SUCCESS(
                f"Per-teacher compaction complete: teachers={len(teacher_ids)}, "
                f"workers={effective_workers}, "
                f"runs={totals['run_count']}, "
                f"archives_verified={totals['archive_runs_verified']}, "
                f"turns_deleted={totals['turn_rows_deleted']}, "
                f"triggers_deleted={totals['trigger_rows_deleted']}"
            )
        )

    def _run_slices_sequential(
        self, teacher_ids, week_start, week_end, options, compaction
    ):
        slice_results = []
        for index, teacher_id in enumerate(teacher_ids, start=1):
            self.stdout.write(
                f"  [{index}/{len(teacher_ids)}] teacher_id={teacher_id}"
            )
            slice_results.append(
                self._compact_slice(
                    week_start,
                    week_end,
                    teacher_id=teacher_id,
                    options=options,
                    week_record=compaction,
                )
            )
        return slice_results

    # --------------------------------------------------------------
    # Parallel orchestrator — bounded subprocess pool. Each child is
    # `manage.py compact_weekly_runs <week> --teacher-id N
    # --skip-verification --emit-json-result`, giving full isolation of
    # Python heap, PG connection, and accumulator dicts per slice. Parent
    # parses each child's stdout for the JSON sentinel line and aggregates.
    # --------------------------------------------------------------

    def _run_slices_parallel(
        self, teacher_ids, week_start, max_workers, options
    ):
        slice_results = [None] * len(teacher_ids)
        pending = list(enumerate(teacher_ids))
        in_flight = {}  # subprocess.Popen -> (index, teacher_id)
        completed = 0
        total = len(teacher_ids)

        try:
            while pending or in_flight:
                while pending and len(in_flight) < max_workers:
                    index, teacher_id = pending.pop(0)
                    proc = self._spawn_slice_worker(
                        week_start, teacher_id, options
                    )
                    in_flight[proc] = (index, teacher_id)

                proc = self._wait_one(in_flight)
                index, teacher_id = in_flight.pop(proc)
                stdout, stderr = proc.communicate()
                completed += 1
                self.stdout.write(
                    f"  [{completed}/{total}] teacher_id={teacher_id} "
                    f"(exit={proc.returncode})"
                )
                if proc.returncode != 0:
                    raise CommandError(
                        f"Per-teacher worker failed for teacher_id={teacher_id}: "
                        f"exit={proc.returncode}\nstderr tail:\n"
                        f"{(stderr or '')[-2000:]}"
                    )
                slice_results[index] = self._parse_slice_result(
                    stdout, teacher_id
                )
        finally:
            for proc in list(in_flight):
                try:
                    proc.kill()
                except OSError:
                    pass

        return slice_results

    @staticmethod
    def _wait_one(in_flight):
        # Poll the in-flight set until at least one finishes. subprocess
        # has no built-in "wait for any" on Windows; on POSIX we'd reach
        # for os.wait() but a short poll is portable and the slices take
        # seconds-to-minutes so the overhead is negligible.
        import time
        while True:
            for proc in in_flight:
                if proc.poll() is not None:
                    return proc
            time.sleep(0.25)

    def _spawn_slice_worker(self, week_start, teacher_id, options):
        # sys.argv[0] is manage.py when invoked via `python manage.py ...`,
        # which is the docker container's normal entry path.
        argv = [
            sys.executable,
            sys.argv[0],
            "compact_weekly_runs",
            week_start.isoformat(),
            "--teacher-id",
            str(teacher_id),
            "--skip-verification",
            "--emit-json-result",
        ]
        if options["dry_run"]:
            argv.append("--dry-run")
        if options["overwrite_archives"]:
            argv.append("--overwrite-archives")
        if options["clear_game_map"]:
            argv.append("--clear-game-map")
        return subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
            text=True,
        )

    @staticmethod
    def _parse_slice_result(stdout, teacher_id):
        if not stdout:
            raise CommandError(
                f"Worker for teacher_id={teacher_id} produced no stdout; "
                f"cannot recover slice result"
            )
        for line in reversed(stdout.splitlines()):
            if line.startswith(SLICE_RESULT_SENTINEL):
                payload = line[len(SLICE_RESULT_SENTINEL):].strip()
                try:
                    return json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise CommandError(
                        f"Worker for teacher_id={teacher_id} emitted "
                        f"malformed slice result JSON: {exc}"
                    ) from exc
        raise CommandError(
            f"Worker for teacher_id={teacher_id} did not emit a "
            f"{SLICE_RESULT_SENTINEL} line"
        )

    # --------------------------------------------------------------
    # WeeklyCompactionRun bookkeeping
    # --------------------------------------------------------------

    def _open_week_compaction_record(self, week_start, week_end):
        compaction, _ = WeeklyCompactionRun.objects.get_or_create(
            week_start=week_start,
            defaults={"week_end": week_end},
        )
        if compaction.status == WeeklyCompactionRun.Status.COMPACTED:
            self.stdout.write(self.style.WARNING("Week is already compacted"))
            return None
        compaction.week_end = week_end
        compaction.started_at = timezone.now()
        compaction.status = WeeklyCompactionRun.Status.PENDING
        compaction.notes = ""
        compaction.save()
        return compaction

    def _finalize_week_record(
        self, compaction, slice_results, week_start, week_end, options
    ):
        totals = self._sum_slice_results(slice_results)
        compaction.run_count = totals["run_count"]
        compaction.turn_count = totals["turn_count"]
        compaction.trigger_count = totals["trigger_count"]
        compaction.archive_runs_written = totals["archive_runs_written"]
        compaction.archive_runs_verified = totals["archive_runs_verified"]
        compaction.archive_bytes_written = totals["archive_bytes_written"]
        compaction.turn_rows_deleted = totals["turn_rows_deleted"]
        compaction.trigger_rows_deleted = totals["trigger_rows_deleted"]
        compaction.completed_at = timezone.now()
        if options["dry_run"]:
            compaction.notes = (
                f"Dry run complete. runs={totals['run_count']}, "
                f"verified_archives={totals['archive_runs_verified']}"
            )
        else:
            compaction.status = WeeklyCompactionRun.Status.COMPACTED
            compaction.notes = (
                f"Compaction complete for {week_start} through {week_end}"
            )
        compaction.save()

    @staticmethod
    def _sum_slice_results(slice_results):
        keys = [
            "run_count", "turn_count", "trigger_count",
            "archive_runs_written", "archive_runs_verified",
            "archive_bytes_written", "turn_rows_deleted",
            "trigger_rows_deleted",
        ]
        totals = {key: 0 for key in keys}
        for slice_result in slice_results:
            for key in keys:
                totals[key] += slice_result.get(key, 0) or 0
        return totals

    @staticmethod
    def _format_summary(slice_result, scope):
        return (
            f"Compaction complete ({scope}): "
            f"runs={slice_result.get('run_count', 0)}, "
            f"archives_verified={slice_result.get('archive_runs_verified', 0)}, "
            f"turns_deleted={slice_result.get('turn_rows_deleted', 0)}, "
            f"triggers_deleted={slice_result.get('trigger_rows_deleted', 0)}"
        )

    @staticmethod
    def _invalidate_dashboard_cache():
        # delete_pattern is a django-redis extension; skip when the cache
        # backend doesn't provide it (e.g. DummyCache under the benchmark
        # dummy-cache overlay, where there is nothing to invalidate).
        if hasattr(cache, "delete_pattern"):
            cache.delete_pattern("teacher_stats_viz:*")
            cache.delete_pattern("teacher_dashboard:*")

    # --------------------------------------------------------------
    # Slice work — does aggregation + archive write + run-bucket rebuild
    # + raw-row delete for one (week, teacher_id) pair. teacher_id=None
    # means "the whole week as one slice", preserving the original
    # invocation shape for callers that don't opt into per-teacher mode.
    # --------------------------------------------------------------

    def _compact_slice(
        self, week_start, week_end, teacher_id, options, week_record
    ):
        runs_qs = (
            Run.objects.filter(
                created_at__date__gte=week_start,
                created_at__date__lte=week_end,
            )
            .select_related("student__classroom")
            .order_by("created_at", "id")
        )
        if teacher_id is not None:
            runs_qs = runs_qs.filter(
                student__classroom__teacher_id=teacher_id
            )

        run_count_total = runs_qs.count()
        if run_count_total == 0:
            self.stdout.write(
                self.style.WARNING(
                    "No runs to compact for this slice"
                    + (f" (teacher_id={teacher_id})" if teacher_id else "")
                )
            )
            return self._empty_slice_result()

        rollup_result = aggregate_weekly_rollups(
            week_start, teacher_id=teacher_id
        )
        _log_compaction_event(
            "weekly_compaction_aggregation_result",
            week_start=str(week_start),
            teacher_id=teacher_id,
            result=rollup_result,
        )

        # Subquery-shaped filter so we don't pass tens of thousands of IDs
        # to PG in one IN clause. The created_at index covers it.
        runs_in_slice = Run.objects.filter(
            created_at__date__gte=week_start,
            created_at__date__lte=week_end,
        )
        if teacher_id is not None:
            runs_in_slice = runs_in_slice.filter(
                student__classroom__teacher_id=teacher_id
            )

        slice_turn_count = TurnEvent.objects.filter(run__in=runs_in_slice).count()
        slice_trigger_count = SpecialTileTrigger.objects.filter(
            turn__run__in=runs_in_slice
        ).count()

        if week_record is not None and teacher_id is None:
            # Single-slice whole-week mode: surface the aggregation
            # checkpoint on the week record so observers see progress.
            week_record.status = WeeklyCompactionRun.Status.AGGREGATED
            week_record.run_count = run_count_total
            week_record.turn_count = slice_turn_count
            week_record.trigger_count = slice_trigger_count
            week_record.save()

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
                    teacher_id=teacher_id,
                    run_id=run.id,
                    storage_path=archive.storage_path,
                    checksum_sha256=archive.checksum_sha256,
                    compressed_size_bytes=archive.compressed_size_bytes,
                )

            archive_is_valid = verify_replay_archive(archive)
            _log_compaction_event(
                "weekly_compaction_archive_verification_result",
                week_start=str(week_start),
                teacher_id=teacher_id,
                run_id=run.id,
                verified=archive_is_valid,
                archive_status=archive.archive_status,
                verification_error=archive.verification_error,
            )
            if archive_is_valid:
                archive_runs_verified += 1
            else:
                if week_record is not None:
                    week_record.status = WeeklyCompactionRun.Status.FAILED
                    week_record.notes = (
                        f"Archive verification failed for run {run.id}"
                        + (f" (teacher_id={teacher_id})" if teacher_id else "")
                    )
                    week_record.completed_at = timezone.now()
                    week_record.save()
                raise CommandError(
                    f"Archive verification failed for run {run.id}"
                )

        run_bucket_result = rebuild_historical_run_bucket_trends(
            student_level_pairs,
            include_run_ids=run_ids,
        )
        _log_compaction_event(
            "weekly_compaction_run_bucket_result",
            week_start=str(week_start),
            teacher_id=teacher_id,
            result=run_bucket_result,
        )

        if options["dry_run"]:
            return {
                "run_count": run_count_total,
                "turn_count": slice_turn_count,
                "trigger_count": slice_trigger_count,
                "archive_runs_written": archive_runs_written,
                "archive_runs_verified": archive_runs_verified,
                "archive_bytes_written": archive_bytes_written,
                "turn_rows_deleted": 0,
                "trigger_rows_deleted": 0,
            }

        # Verify rollups against the still-present raw rows BEFORE deleting.
        # The verifier computes "raw" totals by querying TurnEvent /
        # SpecialTileTrigger; running it post-delete reports raw=0 for every
        # field and flags the rollups (correctly populated) as mismatched.
        # When this slice is one teacher in per-teacher mode, scope the
        # verifier to that teacher so the other teachers' un-yet-aggregated
        # rollups don't get counted as missing.
        if not options["skip_verification"]:
            verify_argv = [
                "verify_weekly_rollups",
                week_start.isoformat(),
                "--require-archives",
                "--verify-run-buckets",
            ]
            if teacher_id is not None:
                verify_argv.extend(["--teacher-id", str(teacher_id)])
            call_command(*verify_argv)

        with transaction.atomic():
            trigger_rows_deleted, _ = SpecialTileTrigger.objects.filter(
                turn__run__in=runs_in_slice
            ).delete()
            turn_rows_deleted, _ = TurnEvent.objects.filter(
                run__in=runs_in_slice
            ).delete()
            update_values = {"raw_data_compacted_at": timezone.now()}
            if options["clear_game_map"]:
                update_values["game_map"] = []
            runs_in_slice.update(**update_values)

        _log_compaction_event(
            "weekly_compaction_delete_result",
            week_start=str(week_start),
            teacher_id=teacher_id,
            trigger_rows_deleted=trigger_rows_deleted,
            turn_rows_deleted=turn_rows_deleted,
            cleared_game_map=options["clear_game_map"],
        )

        return {
            "run_count": run_count_total,
            "turn_count": slice_turn_count,
            "trigger_count": slice_trigger_count,
            "archive_runs_written": archive_runs_written,
            "archive_runs_verified": archive_runs_verified,
            "archive_bytes_written": archive_bytes_written,
            "turn_rows_deleted": turn_rows_deleted,
            "trigger_rows_deleted": trigger_rows_deleted,
        }

    @staticmethod
    def _empty_slice_result():
        return {
            "run_count": 0,
            "turn_count": 0,
            "trigger_count": 0,
            "archive_runs_written": 0,
            "archive_runs_verified": 0,
            "archive_bytes_written": 0,
            "turn_rows_deleted": 0,
            "trigger_rows_deleted": 0,
        }
