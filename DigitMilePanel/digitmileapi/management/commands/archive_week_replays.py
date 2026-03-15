from datetime import date

from django.core.management.base import BaseCommand, CommandError

from digitmileapi.models import ReplayArchive, Run
from digitmileapi.replay_archives import ensure_archive_root, write_replay_archive
from digitmileapi.weekly_rollups import week_end_for, week_start_for


class Command(BaseCommand):
    help = "Archive replay payloads for one historical week"

    def add_arguments(self, parser):
        parser.add_argument(
            "week_start",
            help="Week start date in YYYY-MM-DD format",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Rewrite archives even when a READY archive already exists",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be archived without writing files",
        )

    def handle(self, *args, **options):
        try:
            requested_week_start = date.fromisoformat(options["week_start"])
        except ValueError as exc:
            raise CommandError("week_start must be YYYY-MM-DD") from exc

        week_start = week_start_for(requested_week_start)
        week_end = week_end_for(week_start)
        runs = Run.objects.filter(
            created_at__date__gte=week_start,
            created_at__date__lte=week_end,
        ).select_related("student", "student__classroom")

        if not runs.exists():
            self.stdout.write(self.style.WARNING("No runs found for the requested week"))
            return

        ensure_archive_root()
        archived = 0
        skipped = 0

        for run in runs.iterator(chunk_size=200):
            existing_archive = getattr(run, "replay_archive", None)
            if (
                existing_archive
                and existing_archive.archive_status == ReplayArchive.ArchiveStatus.READY
                and existing_archive.storage_path
                and not options["overwrite"]
            ):
                skipped += 1
                continue

            if options["dry_run"]:
                archived += 1
                continue

            write_replay_archive(run)
            archived += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Archive week complete: week_start={week_start}, archived={archived}, skipped={skipped}"
            )
        )
