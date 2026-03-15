import json
import logging
import statistics
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.conf import settings
from django.db.models import Sum

from digitmileapi.models import Classroom, ReplayArchive, Teacher
from digitmileapi.views import (
    _build_classroom_dashboard_stats,
    _build_student_dashboard_info,
    _build_teacher_statistics_viz_payload,
    _get_filtered_students_for_teacher,
)


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Benchmark teacher analytics helpers against current dataset"

    def add_arguments(self, parser):
        parser.add_argument("teacher_id", help="Teacher id to benchmark")
        parser.add_argument("--grade", dest="grade_filter")
        parser.add_argument("--classroom", dest="classroom_filter")
        parser.add_argument("--iterations", type=int, default=5)
        parser.add_argument("--scenario-name", default="baseline_teacher_analytics")
        parser.add_argument("--output", default="")

    def _timed(self, label, func):
        started = time.perf_counter()
        result = func()
        elapsed_ms = (time.perf_counter() - started) * 1000
        return label, elapsed_ms, result

    def _summary(self, values):
        ordered = sorted(values)
        return {
            "count": len(ordered),
            "avg": round(sum(ordered) / len(ordered), 2),
            "p50": round(statistics.quantiles(ordered, n=100)[49], 2)
            if len(ordered) > 1
            else round(ordered[0], 2),
            "p95": round(statistics.quantiles(ordered, n=100)[94], 2)
            if len(ordered) > 1
            else round(ordered[0], 2),
            "p99": round(statistics.quantiles(ordered, n=100)[98], 2)
            if len(ordered) > 1
            else round(ordered[0], 2),
            "min": round(ordered[0], 2),
            "max": round(ordered[-1], 2),
        }

    def handle(self, *args, **options):
        if options["iterations"] <= 0:
            raise CommandError("--iterations must be positive")

        try:
            teacher = Teacher.objects.get(id=options["teacher_id"])
        except Teacher.DoesNotExist as exc:
            raise CommandError("Teacher not found") from exc

        logger.info(
            "benchmark_scenario_start %s",
            {
                "scenario_name": options["scenario_name"],
                "teacher_id": teacher.id,
                "iterations": options["iterations"],
                "grade_filter": options.get("grade_filter"),
                "classroom_filter": options.get("classroom_filter"),
            },
        )

        students = _get_filtered_students_for_teacher(
            teacher=teacher,
            grade_filter=options.get("grade_filter"),
            classroom_filter=options.get("classroom_filter"),
        )
        student_ids = list(students.values_list("id", flat=True))
        classrooms = Classroom.objects.filter(teacher=teacher)
        if options.get("classroom_filter"):
            classrooms = classrooms.filter(id=options["classroom_filter"])

        measurement_series = {
            "analytics_payload": [],
            "turn_insights_payload": [],
            "student_dashboard_summaries": [],
            "classroom_dashboard_summaries": [],
        }
        for _ in range(options["iterations"]):
            measurement_series["analytics_payload"].append(
                self._timed(
                    "analytics_payload",
                    lambda: _build_teacher_statistics_viz_payload(
                        "analytics",
                        student_ids,
                    ),
                )[1]
            )
            measurement_series["turn_insights_payload"].append(
                self._timed(
                    "turn_insights_payload",
                    lambda: _build_teacher_statistics_viz_payload(
                        "turn_insights",
                        student_ids,
                    ),
                )[1]
            )
            measurement_series["student_dashboard_summaries"].append(
                self._timed(
                    "student_dashboard_summaries",
                    lambda: [
                        _build_student_dashboard_info(student)
                        for student in students.select_related("classroom")
                    ],
                )[1]
            )
            measurement_series["classroom_dashboard_summaries"].append(
                self._timed(
                    "classroom_dashboard_summaries",
                    lambda: [
                        _build_classroom_dashboard_stats(
                            classroom,
                            grade_filter=options.get("grade_filter"),
                        )
                        for classroom in classrooms
                    ],
                )[1]
            )

        table_sizes = {}
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                for table in [
                    "digitmileapi_run",
                    "digitmileapi_turnevent",
                    "digitmileapi_specialtiletrigger",
                    "digitmileapi_studentweekstats",
                    "digitmileapi_studentweeklevelstats",
                    "digitmileapi_studentweekcardtypestats",
                    "digitmileapi_studentrunbuckettrend",
                    "digitmileapi_classroomweekstats",
                    "digitmileapi_replayarchive",
                ]:
                    cursor.execute(
                        "SELECT COALESCE(pg_total_relation_size(%s), 0)",
                        [table],
                    )
                    table_sizes[table] = cursor.fetchone()[0]

        archive_totals = ReplayArchive.objects.aggregate(
            compressed_size_bytes=Sum("compressed_size_bytes"),
            uncompressed_size_bytes=Sum("uncompressed_size_bytes"),
        )
        archive_root = Path(settings.REPLAY_ARCHIVE_ROOT)
        archive_directory_size = 0
        if archive_root.exists():
            archive_directory_size = sum(
                path.stat().st_size
                for path in archive_root.rglob("*")
                if path.is_file()
            )

        report = {
            "scenario_name": options["scenario_name"],
            "teacher_id": teacher.id,
            "iterations": options["iterations"],
            "student_count": len(student_ids),
            "classroom_count": classrooms.count(),
            "measurements_ms": {
                label: self._summary(values)
                for label, values in measurement_series.items()
            },
            "table_sizes_bytes": table_sizes,
            "archive_directory_size_bytes": archive_directory_size,
            "archive_totals": {
                "compressed_size_bytes": archive_totals["compressed_size_bytes"] or 0,
                "uncompressed_size_bytes": archive_totals["uncompressed_size_bytes"]
                or 0,
            },
        }
        report_text = json.dumps(report, indent=2, default=str)
        if options["output"]:
            output_path = Path(options["output"])
            if not output_path.is_absolute():
                output_path = Path.cwd() / output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report_text + "\n", encoding="utf-8")

        logger.info(
            "benchmark_scenario_complete %s",
            {
                "scenario_name": options["scenario_name"],
                "teacher_id": teacher.id,
                "measurements_ms": report["measurements_ms"],
            },
        )
        self.stdout.write(report_text)
