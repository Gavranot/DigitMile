from datetime import date
import logging

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from digitmileapi.models import Run, WeeklyCompactionRun
from digitmileapi.run_bucket_trends import rebuild_historical_run_bucket_trends
from digitmileapi.weekly_aggregation import aggregate_weekly_rollups
from digitmileapi.weekly_rollups import week_end_for, week_start_for


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Rebuild weekly rollup tables for one week from raw gameplay rows"

    def add_arguments(self, parser):
        parser.add_argument("week_start", help="Week start date in YYYY-MM-DD format")
        parser.add_argument(
            "--update-compaction",
            action="store_true",
            help="Update WeeklyCompactionRun status to AGGREGATED",
        )
        parser.add_argument(
            "--rebuild-run-buckets",
            action="store_true",
            help="Rebuild historical run-bucket trends for student-level pairs touched by this week",
        )

    def handle(self, *args, **options):
        try:
            requested_week_start = date.fromisoformat(options["week_start"])
        except ValueError as exc:
            raise CommandError("week_start must be YYYY-MM-DD") from exc

        week_start = week_start_for(requested_week_start)
        week_end = week_end_for(week_start)
        logger.info(
            "weekly_rollup_rebuild_start %s",
            {"week_start": str(week_start), "week_end": str(week_end)},
        )
        result = aggregate_weekly_rollups(week_start)

        if options["rebuild_run_buckets"]:
            week_runs = list(
                Run.objects.filter(
                    created_at__date__gte=week_start,
                    created_at__date__lte=week_end,
                ).only("id", "student_id", "level")
            )
            result["run_bucket_result"] = rebuild_historical_run_bucket_trends(
                {(run.student_id, run.level) for run in week_runs},
                include_run_ids=[run.id for run in week_runs],
            )

        if options["update_compaction"]:
            compaction, _ = WeeklyCompactionRun.objects.get_or_create(
                week_start=week_start,
                defaults={"week_end": week_end},
            )
            compaction.week_end = week_end
            compaction.status = WeeklyCompactionRun.Status.AGGREGATED
            compaction.completed_at = timezone.now()
            compaction.notes = "Rollups rebuilt manually"
            compaction.save()

        logger.info(
            "weekly_rollup_rebuild_complete %s",
            {
                "week_start": str(week_start),
                "week_end": str(week_end),
                "result": result,
            },
        )
        self.stdout.write(self.style.SUCCESS(str(result)))
