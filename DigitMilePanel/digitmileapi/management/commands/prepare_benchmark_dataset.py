import json
import logging
import random
import uuid
from datetime import datetime, time, timedelta
from io import StringIO
from pathlib import Path
from time import perf_counter

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum
from django.utils import timezone

from digitmileapi.models import (
    Classroom,
    ClassroomWeekStats,
    ReplayArchive,
    Run,
    RunStatistics,
    School,
    SpecialTileTrigger,
    Student,
    StudentRunBucketTrend,
    StudentWeekBackCardUsageStats,
    StudentWeekCardFamilyStats,
    StudentWeekCardTypeStats,
    StudentWeekChainLengthStats,
    StudentWeekConditionalStats,
    StudentWeekForeachContextStats,
    StudentWeekHotspotStats,
    StudentWeekLevelStats,
    StudentWeekNumberChoiceStats,
    StudentWeekSpecialTileStats,
    StudentWeekStats,
    Teacher,
    TeacherSchoolAssignment,
    TurnEvent,
    WeeklyCompactionRun,
)
from digitmileapi.weekly_rollups import week_start_for


logger = logging.getLogger(__name__)


BENCHMARK_PASSWORD = "benchmark_password_123"
BENCHMARK_PREFIX = "Benchmark"
CARD_FAMILY_BY_TYPE = {
    "MoveX": "move",
    "IfXMoveYElseMoveZ": "conditional_tile",
    "IfBagEqualXMoveYElseMoveZ": "conditional_bag_eq",
    "IfBagLessXMoveYElseMoveZ": "conditional_bag_lt",
    "IfBagGreaterXMoveYElseMoveZ": "conditional_bag_gt",
    "BagCount": "bagcount",
    "ForXMoveY": "foreach_tile",
    "Back": "back",
}
CARD_MIX_PROFILES = {
    "balanced": [
        ("MoveX", 0.34),
        ("IfXMoveYElseMoveZ", 0.18),
        ("IfBagEqualXMoveYElseMoveZ", 0.08),
        ("IfBagLessXMoveYElseMoveZ", 0.08),
        ("IfBagGreaterXMoveYElseMoveZ", 0.08),
        ("BagCount", 0.06),
        ("ForXMoveY", 0.08),
        ("Back", 0.10),
    ],
    "move_heavy": [
        ("MoveX", 0.52),
        ("IfXMoveYElseMoveZ", 0.14),
        ("IfBagEqualXMoveYElseMoveZ", 0.05),
        ("IfBagLessXMoveYElseMoveZ", 0.05),
        ("IfBagGreaterXMoveYElseMoveZ", 0.05),
        ("BagCount", 0.04),
        ("ForXMoveY", 0.04),
        ("Back", 0.11),
    ],
    "bag_heavy": [
        ("MoveX", 0.20),
        ("IfXMoveYElseMoveZ", 0.14),
        ("IfBagEqualXMoveYElseMoveZ", 0.14),
        ("IfBagLessXMoveYElseMoveZ", 0.14),
        ("IfBagGreaterXMoveYElseMoveZ", 0.14),
        ("BagCount", 0.08),
        ("ForXMoveY", 0.06),
        ("Back", 0.10),
    ],
}


class Command(BaseCommand):
    help = "Prepare a reproducible benchmark dataset and optionally compact historical weeks"

    def _log_progress(self, event, **context):
        logger.info("%s %s", event, context or {})

    def add_arguments(self, parser):
        parser.add_argument("--teachers", type=int, required=True)
        parser.add_argument("--classrooms-per-teacher", type=int, required=True)
        parser.add_argument("--students-per-classroom", type=int, required=True)
        parser.add_argument("--weeks", type=int, required=True)
        parser.add_argument("--runs-per-student-per-week", type=int, required=True)
        parser.add_argument("--avg-turns-per-run", type=int, required=True)
        parser.add_argument(
            "--card-mix-profile",
            choices=sorted(CARD_MIX_PROFILES.keys()),
            default="balanced",
        )
        parser.add_argument("--bag-level-ratio", type=float, default=0.35)
        parser.add_argument(
            "--compact-weeks",
            default="",
            help="Comma-separated oldest-first week indices or ranges, for example 1-8,10. Defaults to all non-hot weeks.",
        )
        parser.add_argument("--hot-weeks", type=int, default=1)
        parser.add_argument(
            "--anchor-week-start",
            default="",
            help="Benchmark anchor week start date; normalized to the Monday of that week (YYYY-MM-DD)",
        )
        parser.add_argument("--clear", action="store_true")
        parser.add_argument("--seed", type=int, default=20260312)
        parser.add_argument("--output", default="")

    def handle(self, *args, **options):
        self._log_progress(
            "benchmark_dataset_preparation_start",
            teachers=options["teachers"],
            classrooms_per_teacher=options["classrooms_per_teacher"],
            students_per_classroom=options["students_per_classroom"],
            weeks=options["weeks"],
            runs_per_student_per_week=options["runs_per_student_per_week"],
            avg_turns_per_run=options["avg_turns_per_run"],
            card_mix_profile=options["card_mix_profile"],
            bag_level_ratio=options["bag_level_ratio"],
            compact_weeks=options["compact_weeks"],
            hot_weeks=options["hot_weeks"],
        )

        if options["weeks"] <= 0:
            raise CommandError("--weeks must be positive")
        if options["hot_weeks"] < 0 or options["hot_weeks"] > options["weeks"]:
            raise CommandError("--hot-weeks must be between 0 and --weeks")
        if not 0 <= options["bag_level_ratio"] <= 1:
            raise CommandError("--bag-level-ratio must be between 0 and 1")

        self.rng = random.Random(options["seed"])
        self.card_mix_profile = options["card_mix_profile"]
        self.avg_turns_per_run = max(1, options["avg_turns_per_run"])
        self.bag_level_ratio = options["bag_level_ratio"]
        self.game_map = self._build_game_map()
        self.tile_type_by_index = {
            tile["tileMapIndex"]: tile["tileType"] for tile in self.game_map
        }
        self.anchor_week_start = self._anchor_week_start(options["anchor_week_start"])

        if options["clear"]:
            self._log_progress("benchmark_dataset_clear_start")
            self._clear_existing_benchmark_data()
            self._log_progress("benchmark_dataset_clear_complete")

        school = self._create_school()
        self._log_progress("benchmark_dataset_school_created", school_id=school.id)
        teachers = self._create_teachers(school, options["teachers"])
        self._log_progress(
            "benchmark_dataset_teachers_created",
            teacher_count=len(teachers),
        )
        classrooms = self._create_classrooms(
            school,
            teachers,
            options["classrooms_per_teacher"],
        )
        self._log_progress(
            "benchmark_dataset_classrooms_created",
            classroom_count=len(classrooms),
        )
        students = self._create_students(
            classrooms,
            options["students_per_classroom"],
        )
        self._log_progress(
            "benchmark_dataset_students_created",
            student_count=len(students),
        )
        week_starts = self._week_starts(options["weeks"])
        compact_week_starts = self._resolve_compact_week_starts(
            week_starts,
            options["compact_weeks"],
            options["hot_weeks"],
        )
        hot_week_starts = [
            week_start
            for week_start in week_starts
            if week_start not in compact_week_starts
        ]
        active_hot_week_start = (
            hot_week_starts[-1] if hot_week_starts else week_starts[-1]
        )
        synthetic_week_close_at = timezone.make_aware(
            datetime.combine(active_hot_week_start + timedelta(days=4), time(20, 0)),
            timezone.get_current_timezone(),
        )
        synthetic_now = synthetic_week_close_at - timedelta(hours=1)
        self._log_progress(
            "benchmark_dataset_generation_plan",
            anchor_week_start=self.anchor_week_start.isoformat(),
            week_count=len(week_starts),
            hot_week_count=len(hot_week_starts),
            compact_week_count=len(compact_week_starts),
            expected_runs=len(students)
            * len(week_starts)
            * options["runs_per_student_per_week"],
            approx_expected_turns=(
                len(students)
                * len(week_starts)
                * options["runs_per_student_per_week"]
                * self.avg_turns_per_run
            ),
        )
        dataset_report = self._generate_runs(
            students=students,
            week_starts=week_starts,
            hot_week_starts=set(hot_week_starts),
            runs_per_student_per_week=options["runs_per_student_per_week"],
        )
        compaction_reports = self._compact_weeks(compact_week_starts)
        archive_totals = ReplayArchive.objects.aggregate(
            compressed=Sum("compressed_size_bytes"),
            uncompressed=Sum("uncompressed_size_bytes"),
        )

        report = {
            "seed": options["seed"],
            "anchor_week_start": self.anchor_week_start.isoformat(),
            "hot_week_start": active_hot_week_start.isoformat(),
            "hot_week_end": (active_hot_week_start + timedelta(days=6)).isoformat(),
            "synthetic_now": synthetic_now.isoformat(),
            "synthetic_week_close_at": synthetic_week_close_at.isoformat(),
            "teacher_password": BENCHMARK_PASSWORD,
            "teachers": [
                {
                    "teacher_id": teacher.id,
                    "username": teacher.user.username if teacher.user else "",
                    "email": teacher.email,
                    "classroom_ids": list(
                        Classroom.objects.filter(teacher=teacher).values_list(
                            "id", flat=True
                        )
                    ),
                }
                for teacher in teachers
            ],
            "counts": {
                "schools": 1,
                "teachers": len(teachers),
                "classrooms": len(classrooms),
                "students": len(students),
                "runs": dataset_report["run_count"],
                "turns": dataset_report["turn_count"],
                "triggers": dataset_report["trigger_count"],
            },
            "weeks": [
                {
                    "index": index + 1,
                    "week_start": week_start.isoformat(),
                    "compacted": week_start in compact_week_starts,
                    "hot": week_start not in compact_week_starts,
                }
                for index, week_start in enumerate(week_starts)
            ],
            "compactions": compaction_reports,
            "archive": {
                "compressed_size_bytes": archive_totals["compressed"] or 0,
                "uncompressed_size_bytes": archive_totals["uncompressed"] or 0,
            },
            "ingest_targets": dataset_report["ingest_targets"],
            "ingest_targets_hot_week": dataset_report["ingest_targets_hot_week"],
            "replay_run_ids": dataset_report["replay_run_ids"],
            "replay_targets_hot": dataset_report["replay_targets_hot"],
            "replay_targets_cold": dataset_report["replay_targets_cold"],
            "teacher_targets": dataset_report["teacher_targets"],
            "dashboard_filter_targets": dataset_report["dashboard_filter_targets"],
            "classrooms": [
                {
                    "classroom_id": classroom.id,
                    "classroom_key": classroom.classroom_key,
                    "teacher_id": classroom.teacher_id,
                    "grade": classroom.grade,
                }
                for classroom in classrooms
            ],
        }
        report_text = json.dumps(report, indent=2, default=str)
        if options["output"]:
            output_path = Path(options["output"])
            if not output_path.is_absolute():
                output_path = Path.cwd() / output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report_text + "\n", encoding="utf-8")

        self._log_progress(
            "benchmark_dataset_preparation_complete",
            runs=report["counts"]["runs"],
            turns=report["counts"]["turns"],
            triggers=report["counts"]["triggers"],
            anchor_week_start=report["anchor_week_start"],
            hot_week_start=report["hot_week_start"],
            synthetic_now=report["synthetic_now"],
            compacted_weeks=[value.isoformat() for value in compact_week_starts],
            output=options["output"],
        )
        self.stdout.write(report_text)

    def _anchor_week_start(self, anchor_week_start_value):
        if anchor_week_start_value:
            try:
                anchor_date = datetime.strptime(
                    anchor_week_start_value, "%Y-%m-%d"
                ).date()
            except ValueError as exc:
                raise CommandError(
                    "--anchor-week-start must be in YYYY-MM-DD format"
                ) from exc
            return week_start_for(anchor_date)

        return week_start_for(timezone.now().date())

    def _clear_existing_benchmark_data(self):
        benchmark_users = list(
            User.objects.filter(username__startswith="benchmark_teacher_")
        )
        benchmark_teachers = Teacher.objects.filter(email__icontains="benchmark")
        benchmark_schools = School.objects.filter(name__startswith=BENCHMARK_PREFIX)
        benchmark_classrooms = Classroom.objects.filter(
            classroom_key__startswith="BMK-"
        )
        benchmark_students = Student.objects.filter(
            full_name__startswith="Benchmark Student"
        )
        benchmark_week_starts = {
            week_start_for(value)
            for value in Run.objects.filter(student__in=benchmark_students).values_list(
                "created_at__date",
                flat=True,
            )
            if value is not None
        }

        self._log_progress(
            "benchmark_dataset_clear_targets",
            school_count=benchmark_schools.count(),
            teacher_count=benchmark_teachers.count(),
            classroom_count=benchmark_classrooms.count(),
            student_count=benchmark_students.count(),
            existing_week_count=len(benchmark_week_starts),
        )

        ReplayArchive.objects.filter(run__student__in=benchmark_students).delete()
        SpecialTileTrigger.objects.filter(
            turn__run__student__in=benchmark_students
        ).delete()
        TurnEvent.objects.filter(run__student__in=benchmark_students).delete()
        Run.objects.filter(student__in=benchmark_students).delete()
        RunStatistics.objects.filter(student__in=benchmark_students).delete()
        StudentRunBucketTrend.objects.filter(student__in=benchmark_students).delete()
        StudentWeekBackCardUsageStats.objects.filter(
            student__in=benchmark_students
        ).delete()
        StudentWeekCardFamilyStats.objects.filter(
            student__in=benchmark_students
        ).delete()
        StudentWeekCardTypeStats.objects.filter(student__in=benchmark_students).delete()
        StudentWeekChainLengthStats.objects.filter(
            student__in=benchmark_students
        ).delete()
        StudentWeekConditionalStats.objects.filter(
            student__in=benchmark_students
        ).delete()
        StudentWeekForeachContextStats.objects.filter(
            student__in=benchmark_students
        ).delete()
        StudentWeekHotspotStats.objects.filter(student__in=benchmark_students).delete()
        StudentWeekLevelStats.objects.filter(student__in=benchmark_students).delete()
        StudentWeekNumberChoiceStats.objects.filter(
            student__in=benchmark_students
        ).delete()
        StudentWeekSpecialTileStats.objects.filter(
            student__in=benchmark_students
        ).delete()
        StudentWeekStats.objects.filter(student__in=benchmark_students).delete()
        ClassroomWeekStats.objects.filter(classroom__in=benchmark_classrooms).delete()
        WeeklyCompactionRun.objects.filter(
            week_start__in=benchmark_week_starts
        ).delete()
        TeacherSchoolAssignment.objects.filter(teacher__in=benchmark_teachers).delete()
        benchmark_students.delete()
        benchmark_classrooms.delete()
        benchmark_teachers.delete()
        benchmark_schools.delete()
        for user in benchmark_users:
            user.delete()

    def _create_school(self):
        return School.objects.create(
            name=f"{BENCHMARK_PREFIX} Primary School",
            municipality="Benchmark Municipality",
            region="Benchmark Region",
            address="Benchmark Address 1",
            director_name="Benchmark Director",
            school_email="benchmark-school@example.com",
            status="APPROVED",
        )

    def _create_teachers(self, school, teacher_count):
        teachers_group, _ = Group.objects.get_or_create(name="Teachers")
        teachers = []
        for index in range(teacher_count):
            username = f"benchmark_teacher_{index + 1}"
            email = f"benchmark-teacher-{index + 1}@example.com"
            user = User.objects.create_user(
                username=username,
                email=email,
                password=BENCHMARK_PASSWORD,
                first_name="Benchmark",
                last_name=f"Teacher {index + 1}",
                is_active=True,
                is_staff=True,
            )
            user.groups.add(teachers_group)
            teacher = Teacher.objects.create(
                user=user,
                full_name=f"Benchmark Teacher {index + 1}",
                email=email,
                status="APPROVED",
                years_teaching=5 + index,
            )
            TeacherSchoolAssignment.objects.create(
                teacher=teacher,
                school=school,
                years_at_school=2,
            )
            teachers.append(teacher)
        return teachers

    def _create_classrooms(self, school, teachers, classrooms_per_teacher):
        classrooms = []
        for teacher_index, teacher in enumerate(teachers, start=1):
            for classroom_index in range(classrooms_per_teacher):
                grade = 1 + ((teacher_index + classroom_index) % 6)
                classrooms.append(
                    Classroom.objects.create(
                        classroom_key=f"BMK-{teacher_index:02d}{classroom_index + 1:02d}",
                        classroom_name=f"{grade}-{chr(65 + classroom_index)}",
                        grade=grade,
                        teacher=teacher,
                        school=school,
                    )
                )
        return classrooms

    def _create_students(self, classrooms, students_per_classroom):
        students = []
        for classroom in classrooms:
            for index in range(students_per_classroom):
                students.append(
                    Student.objects.create(
                        full_name=f"Benchmark Student {classroom.classroom_name} {index + 1}",
                        grade=classroom.grade,
                        classroom=classroom,
                    )
                )
        return students

    def _week_starts(self, week_count):
        return [
            self.anchor_week_start - timedelta(weeks=offset)
            for offset in range(week_count - 1, -1, -1)
        ]

    def _resolve_compact_week_starts(self, week_starts, compact_weeks, hot_weeks):
        if compact_weeks is not None:
            compact_weeks = str(compact_weeks).strip()
            if compact_weeks.lower() in {"", "none", "off", "false", "no"}:
                return set()

            selected = set()
            for part in compact_weeks.split(","):
                token = part.strip()
                if not token:
                    continue
                if "-" in token:
                    start_value, end_value = token.split("-", 1)
                    for value in range(int(start_value), int(end_value) + 1):
                        selected.add(value)
                else:
                    selected.add(int(token))
            return {
                week_starts[index - 1]
                for index in selected
                if 1 <= index <= len(week_starts)
            }

        if hot_weeks == 0:
            return set(week_starts)
        return set(week_starts[:-hot_weeks])

    def _build_game_map(self):
        tiles = []
        special_by_index = {4: (4, "clown", -4), 8: (5, "skateboard", 5)}
        for tile_index in range(12):
            if tile_index in special_by_index:
                tile_type, special, special_delta = special_by_index[tile_index]
            else:
                tile_type = 0 if tile_index in {0, 11} else (tile_index % 3) + 1
                special = "normal"
                special_delta = 0
            tiles.append(
                {
                    "tileMapIndex": tile_index,
                    "tileIndex": tile_type,
                    "tileType": tile_type,
                    "special": special,
                    "special_delta": special_delta,
                }
            )
        return tiles

    def _serialize_card_data(
        self,
        tile_type=None,
        if_sign=None,
        if_value=None,
        then_value=None,
        else_value=None,
    ):
        return (
            "[CardData: "
            f"tileType={'' if tile_type is None else tile_type}, "
            f"ifSign={'' if if_sign is None else if_sign}, "
            f"ifValue={'' if if_value is None else if_value}, "
            f"thenValue={'' if then_value is None else then_value}, "
            f"elseValue={'' if else_value is None else else_value}]"
        )

    def _weighted_card_type(self, level):
        available = []
        for card_type, weight in CARD_MIX_PROFILES[self.card_mix_profile]:
            if level < 5 and card_type in {
                "IfBagEqualXMoveYElseMoveZ",
                "IfBagLessXMoveYElseMoveZ",
                "IfBagGreaterXMoveYElseMoveZ",
                "BagCount",
            }:
                continue
            available.append((card_type, weight))
        values, weights = zip(*available)
        return self.rng.choices(values, weights=weights, k=1)[0]

    def _build_card(self, card_type, tile_before_type, bag_before):
        move_value = self.rng.randint(1, 4)
        if card_type == "MoveX":
            return {
                "type": card_type,
                "data": self._serialize_card_data(then_value=move_value),
                "tile_type": None,
                "movement": move_value,
            }
        if card_type == "Back":
            return {
                "type": card_type,
                "data": self._serialize_card_data(then_value=2),
                "tile_type": None,
                "movement": -2,
            }
        if card_type == "IfXMoveYElseMoveZ":
            desired_tile_type = tile_before_type if self.rng.random() < 0.5 else 3
            else_value = self.rng.randint(1, 2)
            movement = (
                move_value if tile_before_type == desired_tile_type else else_value
            )
            return {
                "type": card_type,
                "data": self._serialize_card_data(
                    tile_type=desired_tile_type,
                    then_value=move_value,
                    else_value=else_value,
                ),
                "tile_type": desired_tile_type,
                "movement": movement,
            }
        if card_type in {
            "IfBagEqualXMoveYElseMoveZ",
            "IfBagLessXMoveYElseMoveZ",
            "IfBagGreaterXMoveYElseMoveZ",
        }:
            sign_by_type = {
                "IfBagEqualXMoveYElseMoveZ": "==",
                "IfBagLessXMoveYElseMoveZ": "<",
                "IfBagGreaterXMoveYElseMoveZ": ">",
            }
            comparator_value = self.rng.randint(1, 5)
            else_value = self.rng.randint(1, 2)
            if card_type == "IfBagEqualXMoveYElseMoveZ":
                condition_met = bag_before == comparator_value
            elif card_type == "IfBagLessXMoveYElseMoveZ":
                condition_met = bag_before < comparator_value
            else:
                condition_met = bag_before > comparator_value
            movement = move_value if condition_met else else_value
            return {
                "type": card_type,
                "data": self._serialize_card_data(
                    if_sign=sign_by_type[card_type],
                    if_value=comparator_value,
                    then_value=move_value,
                    else_value=else_value,
                ),
                "tile_type": None,
                "movement": movement,
            }
        if card_type == "BagCount":
            return {
                "type": card_type,
                "data": self._serialize_card_data(),
                "tile_type": None,
                "movement": bag_before,
            }
        return {
            "type": "ForXMoveY",
            "data": self._serialize_card_data(
                tile_type=max(1, tile_before_type), then_value=2
            ),
            "tile_type": max(1, tile_before_type),
            "movement": 2,
        }

    def _offered_cards(self, level, tile_before_type, bag_before, chosen_card):
        offered = [{"type": chosen_card["type"], "data": chosen_card["data"]}]
        while len(offered) < 3:
            card_type = self._weighted_card_type(level)
            card = self._build_card(card_type, tile_before_type, bag_before)
            offered.append({"type": card["type"], "data": card["data"]})
        return offered

    def _run_level(self):
        if self.rng.random() < self.bag_level_ratio:
            return self.rng.choice([5, 6])
        return self.rng.choice([1, 2, 3, 4])

    def _generate_runs(
        self, students, week_starts, hot_week_starts, runs_per_student_per_week
    ):
        run_count = 0
        turn_count = 0
        trigger_count = 0
        ingest_targets = []
        ingest_target_ids = set()
        ingest_targets_hot_week = []
        ingest_target_hot_week_ids = set()
        replay_run_ids = []
        replay_targets_hot = []
        replay_targets_cold = []
        teacher_targets = []
        teacher_target_ids = set()
        dashboard_filter_targets = []
        dashboard_filter_ids = set()
        total_students = len(students)
        total_runs_expected = (
            total_students * len(week_starts) * runs_per_student_per_week
        )
        progress_interval = max(250, total_runs_expected // 20 or 1)

        self._log_progress(
            "benchmark_dataset_run_generation_start",
            student_count=total_students,
            week_count=len(week_starts),
            runs_per_student_per_week=runs_per_student_per_week,
            expected_runs=total_runs_expected,
            progress_interval=progress_interval,
        )

        for student in students:
            teacher = student.classroom.teacher
            if teacher.id not in teacher_target_ids:
                teacher_targets.append(
                    {
                        "teacher_id": teacher.id,
                        "username": teacher.user.username if teacher.user else "",
                        "classroom_id": student.classroom.id,
                        "classroom_key": student.classroom.classroom_key,
                    }
                )
                teacher_target_ids.add(teacher.id)
            if student.classroom.id not in dashboard_filter_ids:
                dashboard_filter_targets.append(
                    {
                        "classroom_id": student.classroom.id,
                        "classroom_key": student.classroom.classroom_key,
                        "teacher_id": teacher.id,
                        "grade": student.classroom.grade,
                    }
                )
                dashboard_filter_ids.add(student.classroom.id)

        for student_index, student in enumerate(students, start=1):
            for week_start in week_starts:
                for _ in range(runs_per_student_per_week):
                    level = self._run_level()
                    created_at = timezone.make_aware(
                        datetime.combine(
                            week_start + timedelta(days=self.rng.randint(0, 4)),
                            time(
                                hour=8 + self.rng.randint(0, 8),
                                minute=self.rng.randint(0, 59),
                            ),
                        ),
                        timezone.get_current_timezone(),
                    )
                    turn_total = max(
                        2, self.avg_turns_per_run + self.rng.randint(-1, 2)
                    )
                    player_position = 0
                    bag_number = 1
                    bot_positions = [2, 3]
                    correct_moves = 0
                    wrong_moves = 0
                    run = Run.objects.create(
                        id=f"run_{uuid.uuid4().hex[:32]}",
                        student=student,
                        level=level,
                        player_won=False,
                        score=0,
                        place=4,
                        elapsed_ms=0,
                        correct_moves=0,
                        wrong_moves=0,
                        game_map=self.game_map,
                    )
                    Run.objects.filter(id=run.id).update(
                        created_at=created_at, updated_at=created_at
                    )

                    turn_timestamp = created_at
                    for turn_index in range(turn_total):
                        tile_before_type = self.tile_type_by_index.get(
                            player_position, 0
                        )
                        card_type = self._weighted_card_type(level)
                        card = self._build_card(card_type, tile_before_type, bag_number)
                        was_correct = self.rng.random() < 0.72
                        movement = (
                            card["movement"]
                            if was_correct
                            else max(1, abs(card["movement"]) - 1)
                        )
                        movement = movement if card["movement"] >= 0 else -movement
                        tile_after_index = max(0, min(11, player_position + movement))
                        card_decision_time_ms = self.rng.randint(800, 4000)
                        offered_numbers = []
                        chosen_number = None
                        number_decision_time_ms = None
                        if level >= 5:
                            offered_numbers = self.rng.sample([1, 2, 3, 4, 5], 3)
                            chosen_number = self.rng.choice(offered_numbers)
                            number_decision_time_ms = self.rng.randint(400, 2500)
                            bag_number = chosen_number

                        bot_positions_before = [
                            {"tileMapIndex": value, "botID": f"bot_{index + 1}"}
                            for index, value in enumerate(bot_positions)
                        ]
                        bot_positions = [
                            max(0, min(11, value + self.rng.choice([0, 1, 1, 2])))
                            for value in bot_positions
                        ]
                        bot_positions_after = [
                            {"tileMapIndex": value, "botID": f"bot_{index + 1}"}
                            for index, value in enumerate(bot_positions)
                        ]
                        place_before = 1 + sum(
                            value > player_position for value in bot_positions
                        )
                        place_after = 1 + sum(
                            value > tile_after_index for value in bot_positions
                        )
                        turn = TurnEvent.objects.create(
                            run=run,
                            turn_index=turn_index,
                            timestamp_played=turn_timestamp,
                            chosen_card={"type": card["type"], "data": card["data"]},
                            chosen_card_type=card["type"],
                            chosen_card_family=CARD_FAMILY_BY_TYPE[card["type"]],
                            chosen_card_tile_type=card["tile_type"],
                            offered_cards=self._offered_cards(
                                level, tile_before_type, bag_number, card
                            ),
                            was_correct=was_correct,
                            tile_before_index=player_position,
                            tile_before_type=tile_before_type,
                            tile_after_index=tile_after_index,
                            place_before=place_before,
                            place_after=place_after,
                            bot_positions_before=bot_positions_before,
                            bot_positions_after=bot_positions_after,
                            card_decision_time_ms=card_decision_time_ms,
                            offered_numbers=offered_numbers,
                            chosen_number=chosen_number,
                            number_decision_time_ms=number_decision_time_ms,
                        )
                        turn_count += 1
                        correct_moves += 1 if was_correct else 0
                        wrong_moves += 0 if was_correct else 1

                        tile_after_type = self.tile_type_by_index.get(
                            tile_after_index, 0
                        )
                        special_delta = {4: -4, 5: 5}.get(tile_after_type)
                        if special_delta is not None:
                            target_tile_index = max(
                                0, min(11, tile_after_index + special_delta)
                            )
                            SpecialTileTrigger.objects.create(
                                turn=turn,
                                chain_index=0,
                                special_tile_index=tile_after_index,
                                special_tile_type=tile_after_type,
                                effect_delta_tiles=special_delta,
                                target_tile_index=target_tile_index,
                                target_tile_type=self.tile_type_by_index.get(
                                    target_tile_index, 0
                                ),
                                place_before=place_after,
                                place_after=1
                                + sum(
                                    value > target_tile_index for value in bot_positions
                                ),
                            )
                            trigger_count += 1
                            player_position = target_tile_index
                        else:
                            player_position = tile_after_index

                        turn_timestamp += timedelta(
                            milliseconds=card_decision_time_ms
                            + (number_decision_time_ms or 0)
                        )

                    player_won = player_position >= 10 or self.rng.random() < 0.4
                    place = 1 if player_won else self.rng.randint(2, 4)
                    score = max(
                        0,
                        (correct_moves * 25)
                        - (wrong_moves * 8)
                        + (180 if player_won else 60),
                    )
                    elapsed_ms = max(
                        1000, int((turn_timestamp - created_at).total_seconds() * 1000)
                    )
                    Run.objects.filter(id=run.id).update(
                        player_won=player_won,
                        place=place,
                        score=score,
                        elapsed_ms=elapsed_ms,
                        correct_moves=correct_moves,
                        wrong_moves=wrong_moves,
                    )
                    run_count += 1
                    ingest_target = {
                        "student_id": student.id,
                        "student_name": student.full_name,
                        "classroom_key": student.classroom.classroom_key,
                    }
                    if student.id not in ingest_target_ids:
                        ingest_targets.append(ingest_target)
                        ingest_target_ids.add(student.id)
                    if (
                        week_start in hot_week_starts
                        and student.id not in ingest_target_hot_week_ids
                    ):
                        ingest_targets_hot_week.append(ingest_target)
                        ingest_target_hot_week_ids.add(student.id)
                    if len(replay_run_ids) < 50:
                        replay_run_ids.append(run.id)
                    replay_target = {
                        "run_id": run.id,
                        "student_id": student.id,
                        "week_start": week_start.isoformat(),
                        "hot": week_start in hot_week_starts,
                    }
                    if week_start in hot_week_starts:
                        if len(replay_targets_hot) < 50:
                            replay_targets_hot.append(replay_target)
                    elif len(replay_targets_cold) < 50:
                        replay_targets_cold.append(replay_target)

                    if run_count % progress_interval == 0:
                        self._log_progress(
                            "benchmark_dataset_run_generation_progress",
                            runs_created=run_count,
                            expected_runs=total_runs_expected,
                            turns_created=turn_count,
                            triggers_created=trigger_count,
                            current_student_index=student_index,
                            total_students=total_students,
                            current_week_start=week_start.isoformat(),
                        )

            if student_index % max(1, total_students // 10 or 1) == 0:
                self._log_progress(
                    "benchmark_dataset_student_progress",
                    students_processed=student_index,
                    total_students=total_students,
                    runs_created=run_count,
                )

        self._log_progress(
            "benchmark_dataset_run_generation_complete",
            runs_created=run_count,
            turns_created=turn_count,
            triggers_created=trigger_count,
        )

        return {
            "run_count": run_count,
            "turn_count": turn_count,
            "trigger_count": trigger_count,
            "ingest_targets": ingest_targets,
            "ingest_targets_hot_week": ingest_targets_hot_week,
            "replay_run_ids": replay_run_ids,
            "replay_targets_hot": replay_targets_hot,
            "replay_targets_cold": replay_targets_cold,
            "teacher_targets": teacher_targets,
            "dashboard_filter_targets": dashboard_filter_targets,
        }

    def _compact_weeks(self, compact_week_starts):
        reports = []
        if compact_week_starts:
            self._log_progress(
                "benchmark_dataset_compaction_start",
                compact_week_count=len(compact_week_starts),
            )
        for week_start in sorted(compact_week_starts):
            started = perf_counter()
            command_output = StringIO()
            self._log_progress(
                "benchmark_dataset_compaction_week_start",
                week_start=week_start.isoformat(),
            )
            call_command(
                "compact_weekly_runs",
                week_start.isoformat(),
                stdout=command_output,
            )
            duration_ms = round((perf_counter() - started) * 1000, 2)
            compaction = WeeklyCompactionRun.objects.get(week_start=week_start)
            reports.append(
                {
                    "week_start": week_start.isoformat(),
                    "duration_ms": duration_ms,
                    "status": compaction.status,
                    "archive_runs_verified": compaction.archive_runs_verified,
                    "turn_rows_deleted": compaction.turn_rows_deleted,
                    "trigger_rows_deleted": compaction.trigger_rows_deleted,
                    "stdout": command_output.getvalue().strip(),
                }
            )
            self._log_progress(
                "benchmark_dataset_compaction_week_complete",
                week_start=week_start.isoformat(),
                duration_ms=duration_ms,
                status=compaction.status,
                turn_rows_deleted=compaction.turn_rows_deleted,
                trigger_rows_deleted=compaction.trigger_rows_deleted,
            )
        if compact_week_starts:
            self._log_progress(
                "benchmark_dataset_compaction_complete",
                compact_week_count=len(compact_week_starts),
            )
        return reports
