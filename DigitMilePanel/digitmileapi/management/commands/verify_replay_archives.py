from datetime import date

from django.core.management.base import BaseCommand, CommandError

from digitmileapi.models import ReplayArchive
from digitmileapi.replay_archives import verify_replay_archive
from digitmileapi.weekly_rollups import week_end_for, week_start_for


class Command(BaseCommand):
    help = "Verify replay archive files and checksums"

    def add_arguments(self, parser):
        parser.add_argument(
            "--week-start",
            dest="week_start",
            help="Optional week start date in YYYY-MM-DD format",
        )

    def handle(self, *args, **options):
        archives = ReplayArchive.objects.select_related("run")

        if options["week_start"]:
            try:
                requested_week_start = date.fromisoformat(options["week_start"])
            except ValueError as exc:
                raise CommandError("week_start must be YYYY-MM-DD") from exc

            week_start = week_start_for(requested_week_start)
            week_end = week_end_for(week_start)
            archives = archives.filter(
                run__created_at__date__gte=week_start,
                run__created_at__date__lte=week_end,
            )

        total = archives.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No replay archives found"))
            return

        verified = 0
        failed = 0

        for archive in archives.iterator(chunk_size=200):
            if verify_replay_archive(archive):
                verified += 1
            else:
                failed += 1

        style = self.style.SUCCESS if failed == 0 else self.style.WARNING
        self.stdout.write(style(f"Replay archive verification complete: verified={verified}, failed={failed}"))
