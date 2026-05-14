"""
Rollup accuracy test: verifies that weekly_aggregation produces rollup data
that yields the same analytics results as computing from hot (raw) data.

Approach:
  1. Create a small dataset (1 teacher, 1 classroom, 5 students, 3 weeks of runs)
  2. All data is hot → call every rollup_analytics function → save results
  3. Compact all 3 weeks (aggregate rollups, delete turns/triggers, mark compacted)
  4. All data is now in rollup tables → call the same functions → save results
  5. Assert the two result sets are identical
"""

import random
from datetime import date, timedelta, timezone as dt_timezone

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.db import transaction
from django.test import TransactionTestCase
from django.utils import timezone as dj_timezone

from digitmileapi.management.commands.seed_database import Command as SeedCommand
from digitmileapi.models import (
    Classroom,
    Run,
    School,
    SpecialTileTrigger,
    Student,
    Teacher,
    TeacherSchoolAssignment,
    TurnEvent,
    WeeklyCompactionRun,
)
from digitmileapi.rollup_analytics import (
    back_card_usage_by_place_by_level,
    bag_conditional_accuracy_by_comparator_by_level,
    card_accuracy_by_family_by_level,
    decision_time_by_card_type,
    decision_time_by_family_by_level,
    foreach_tile_context_usage_by_level,
    mistake_hotspots_by_level,
    number_choice_distribution_by_level,
    number_decision_time_by_choice_by_level,
    offer_choice_share_by_family,
    special_tile_breakdown,
    special_tile_chain_length_distribution_by_level,
    tile_conditional_accuracy_by_tile_type_by_level,
    time_distribution_by_level,
    win_rate_by_level,
    wrong_moves_rate_by_level,
)
from digitmileapi.weekly_aggregation import aggregate_weekly_rollups
from digitmileapi.weekly_rollups import week_end_for, week_start_for


NUM_TEACHERS = 3
NUM_CLASSROOMS_PER_TEACHER = 2
NUM_STUDENTS_PER_CLASSROOM = 5
NUM_WEEKS = 3
RUNS_PER_STUDENT_PER_WEEK = 4
RANDOM_SEED = 42


class RollupAccuracyTest(TransactionTestCase):
    """
    Verifies that the weekly rollup aggregation preserves all information
    needed by the analytics layer. The test compares analytics results
    computed from raw hot data against the same results computed from
    pre-aggregated rollup tables.
    """

    def setUp(self):
        random.seed(RANDOM_SEED)

        school = School.objects.create(
            name="Test School",
            municipality="Centar",
            region="Skopje",
            status="APPROVED",
        )

        teachers_group, _ = Group.objects.get_or_create(name="Teachers")

        # Multi-teacher / multi-classroom topology guards against bugs
        # where a chunked aggregation pass would mis-attribute runs to
        # the wrong (student, classroom, teacher) key tuple. With one
        # teacher every key tuple collapses to identical values and
        # such a bug would be invisible.
        self.students = []
        classroom_counter = 0
        for t_idx in range(NUM_TEACHERS):
            user = User.objects.create_user(
                username=f"test_teacher_{t_idx}",
                email=f"test_teacher_{t_idx}@test.com",
                password="password123",
                is_staff=True,
            )
            user.groups.add(teachers_group)
            teacher = Teacher.objects.create(
                user=user,
                full_name=f"Test Teacher {t_idx}",
                email=f"test_teacher_{t_idx}@test.com",
                status="APPROVED",
            )
            TeacherSchoolAssignment.objects.create(teacher=teacher, school=school)

            for c_idx in range(NUM_CLASSROOMS_PER_TEACHER):
                classroom_counter += 1
                classroom = Classroom.objects.create(
                    classroom_key=f"TST-{classroom_counter:04d}",
                    classroom_name=f"3-{chr(ord('a') + c_idx)}",
                    grade=3,
                    teacher=teacher,
                    school=school,
                )
                for s_idx in range(NUM_STUDENTS_PER_CLASSROOM):
                    student = Student.objects.create(
                        full_name=(
                            f"Teacher {t_idx} Classroom {c_idx} Student {s_idx}"
                        ),
                        date_of_birth=date(2016, 1, 1),
                        grade=3,
                        classroom=classroom,
                    )
                    self.students.append(student)

        # Compute week boundaries: 3 weeks ending with this week.
        anchor = week_start_for(date.today())
        self.weeks = []
        for i in range(NUM_WEEKS):
            offset = NUM_WEEKS - 1 - i
            ws = week_start_for(anchor - timedelta(weeks=offset))
            we = week_end_for(ws)
            self.weeks.append((ws, we))

        # Generate runs using the seed_database game simulation logic.
        seed_cmd = SeedCommand()
        seed_cmd.level_decks = seed_cmd.load_level_decks()

        for ws, we in self.weeks:
            runs_to_create = []
            turns_to_create = []
            triggers_to_create = []

            for student in self.students:
                for _ in range(RUNS_PER_STUDENT_PER_WEEK):
                    run_data = seed_cmd._generate_run_data(
                        student, week_start=ws, week_end=we
                    )
                    runs_to_create.append(run_data["run"])
                    turns_to_create.extend(run_data["turns"])
                    triggers_to_create.extend(run_data["triggers"])

            Run.objects.bulk_create(runs_to_create)
            TurnEvent.objects.bulk_create(turns_to_create)
            if triggers_to_create:
                SpecialTileTrigger.objects.bulk_create(triggers_to_create)

        self.student_ids = [s.id for s in self.students]

        # Sanity check: we have data
        self.assertGreater(Run.objects.count(), 0)
        self.assertGreater(TurnEvent.objects.count(), 0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _all_analytics(self):
        """Call every rollup_analytics function and return a dict of results."""
        ids = self.student_ids
        return {
            "win_rate_by_level": win_rate_by_level(ids),
            "wrong_moves_rate_by_level": wrong_moves_rate_by_level(ids),
            "time_distribution_by_level": time_distribution_by_level(ids),
            "mistake_hotspots_by_level": mistake_hotspots_by_level(ids),
            "special_tile_breakdown": special_tile_breakdown(ids),
            "offer_choice_share_by_family": offer_choice_share_by_family(ids),
            "card_accuracy_by_family_by_level": card_accuracy_by_family_by_level(ids),
            "decision_time_by_family_by_level": decision_time_by_family_by_level(ids),
            "decision_time_by_card_type": decision_time_by_card_type(ids),
            "tile_conditional_accuracy": tile_conditional_accuracy_by_tile_type_by_level(ids),
            "bag_conditional_accuracy": bag_conditional_accuracy_by_comparator_by_level(ids),
            "back_card_usage": back_card_usage_by_place_by_level(ids),
            "foreach_tile_context": foreach_tile_context_usage_by_level(ids),
            "chain_length_distribution": special_tile_chain_length_distribution_by_level(ids),
            "number_choice_distribution": number_choice_distribution_by_level(ids),
            "number_decision_time": number_decision_time_by_choice_by_level(ids),
        }

    def _compact_all_weeks(self):
        """Aggregate rollups and compact all weeks."""
        for ws, we in self.weeks:
            aggregate_weekly_rollups(ws)

            runs = Run.objects.filter(
                created_at__date__gte=ws, created_at__date__lte=we
            )
            run_ids = list(runs.values_list("id", flat=True))

            with transaction.atomic():
                SpecialTileTrigger.objects.filter(turn__run_id__in=run_ids).delete()
                TurnEvent.objects.filter(run_id__in=run_ids).delete()
                runs.update(raw_data_compacted_at=dj_timezone.now())

            WeeklyCompactionRun.objects.create(
                week_start=ws,
                week_end=we,
                status=WeeklyCompactionRun.Status.COMPACTED,
                run_count=len(run_ids),
                completed_at=dj_timezone.now(),
            )

        # Verify compaction actually happened
        self.assertEqual(TurnEvent.objects.count(), 0)
        self.assertEqual(SpecialTileTrigger.objects.count(), 0)
        self.assertTrue(
            Run.objects.filter(raw_data_compacted_at__isnull=False).exists()
        )

    @staticmethod
    def _round_floats(obj, precision=6):
        """Recursively round floats for comparison tolerance."""
        if isinstance(obj, float):
            return round(obj, precision)
        if isinstance(obj, dict):
            return {k: RollupAccuracyTest._round_floats(v, precision) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [RollupAccuracyTest._round_floats(item, precision) for item in obj]
        return obj

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_rollup_matches_hot_data_analytics(self):
        """
        Core test: analytics from all-hot data must equal analytics from
        all-rollup data, for every rollup_analytics function.
        """
        # Step 1: all data is hot — get analytics results.
        hot_results = self._all_analytics()

        # Sanity: at least some results are non-empty.
        self.assertGreater(len(hot_results["win_rate_by_level"]), 0)
        self.assertGreater(len(hot_results["card_accuracy_by_family_by_level"]), 0)

        # Step 2: compact all weeks — data moves to rollup tables.
        self._compact_all_weeks()

        # Step 3: all data is now in rollups — get analytics results.
        rollup_results = self._all_analytics()

        # Step 4: compare every function's output.
        for func_name in hot_results:
            hot = self._round_floats(hot_results[func_name])
            rollup = self._round_floats(rollup_results[func_name])
            self.assertEqual(
                hot,
                rollup,
                f"\n\nMISMATCH in {func_name}:\n"
                f"  hot    = {hot}\n"
                f"  rollup = {rollup}",
            )

    def test_partial_compaction_matches(self):
        """
        Analytics from 2 compacted weeks + 1 hot week should equal
        analytics from 3 hot weeks.
        """
        # Get all-hot baseline.
        hot_results = self._all_analytics()

        # Compact only the first 2 weeks, leaving week 3 hot.
        for ws, we in self.weeks[:2]:
            aggregate_weekly_rollups(ws)
            runs = Run.objects.filter(
                created_at__date__gte=ws, created_at__date__lte=we
            )
            run_ids = list(runs.values_list("id", flat=True))
            with transaction.atomic():
                SpecialTileTrigger.objects.filter(turn__run_id__in=run_ids).delete()
                TurnEvent.objects.filter(run_id__in=run_ids).delete()
                runs.update(raw_data_compacted_at=dj_timezone.now())
            WeeklyCompactionRun.objects.create(
                week_start=ws, week_end=we,
                status=WeeklyCompactionRun.Status.COMPACTED,
                run_count=len(run_ids),
                completed_at=dj_timezone.now(),
            )

        # Now get mixed results (2 weeks rollup + 1 week hot).
        mixed_results = self._all_analytics()

        for func_name in hot_results:
            hot = self._round_floats(hot_results[func_name])
            mixed = self._round_floats(mixed_results[func_name])
            self.assertEqual(
                hot,
                mixed,
                f"\n\nMISMATCH in {func_name} (partial compaction):\n"
                f"  all_hot = {hot}\n"
                f"  mixed   = {mixed}",
            )

    def test_streaming_aggregation_matches_raw_data_verifier(self):
        """
        Direct oracle test for the chunked streaming refactor of
        aggregate_weekly_rollups: run the aggregation with a tiny
        chunk_size (forcing several chunk boundaries against the seeded
        runs), then invoke the production `verify_weekly_rollups`
        management command which compares rollup row counts and sums
        against the raw rows. CommandError on any mismatch.
        """
        # setUp's _generate_run_data does not set created_at (the model
        # has auto_now_add=True; the production seeder backdates via a
        # follow-up SQL UPDATE that setUp skips). So all ~60 seeded runs
        # land in this week — aggregate that one.
        target_week_start, _ = self.weeks[-1]
        # chunk_size=7 forces ~9 chunks across the 60 runs, exercising
        # the chunk-boundary flush path multiple times (the default 500
        # would put everything in a single trailing flush against this
        # dataset and skip the boundary path entirely).
        aggregate_weekly_rollups(target_week_start, chunk_size=7)
        call_command("verify_weekly_rollups", target_week_start.isoformat())
