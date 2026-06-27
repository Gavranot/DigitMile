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
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.db import transaction
from django.db.models import Sum
from django.test import TransactionTestCase, override_settings
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

    def test_analytics_unchanged_when_hot_rows_are_compacted_away(self):
        """
        The analytics layer reads rollup tables only (the "no hot data in
        dashboard" rule). So once a week is aggregated, deleting its hot
        Run/TurnEvent rows during compaction must not change any analytics
        result — the dashboard never read those rows to begin with.

        (This replaces an older hot-vs-rollup parity test: there is no longer a
        "compute from hot data" path to compare against, since every
        rollup_analytics function is rollup-only.)
        """
        # Step 1: aggregate every week into the rollup tables, hot rows intact.
        for week_start, _ in self.weeks:
            aggregate_weekly_rollups(week_start)

        pre_compaction = self._all_analytics()

        # Sanity: rollups are populated, so results are non-empty.
        self.assertGreater(len(pre_compaction["win_rate_by_level"]), 0)
        self.assertGreater(len(pre_compaction["card_accuracy_by_family_by_level"]), 0)

        # Step 2: compact — delete the hot Run/TurnEvent rows.
        self._compact_all_weeks()

        # Step 3: analytics computed from the same rollups must be identical.
        post_compaction = self._all_analytics()

        for func_name in pre_compaction:
            pre = self._round_floats(pre_compaction[func_name])
            post = self._round_floats(post_compaction[func_name])
            self.assertEqual(
                pre,
                post,
                f"\n\nMISMATCH in {func_name}:\n"
                f"  pre-compaction  = {pre}\n"
                f"  post-compaction = {post}",
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

    def test_per_teacher_aggregation_matches_raw_data_verifier(self):
        """
        Run aggregate_weekly_rollups per-teacher (the production-realistic
        invocation pattern at national scale) and confirm the assembled
        week-level rollups still satisfy verify_weekly_rollups.

        Catches three classes of bugs the whole-week path would not:
          1. A per-teacher pass wiping another teacher's rollups during
             its _delete_existing_week_rollups call (would surface as
             undercount in the verifier).
          2. classroom_student_counts being computed only against the
             current teacher's classrooms, leading to wrong student_count
             on ClassroomWeekStats for the other teachers.
          3. Any accumulator that aliases on a key not including
             teacher_id (would conflate rows across teachers).
        """
        target_week_start, _ = self.weeks[-1]
        teacher_ids = list(
            Run.objects.filter(
                created_at__date__gte=target_week_start,
                created_at__date__lte=week_end_for(target_week_start),
            )
            .values_list("student__classroom__teacher_id", flat=True)
            .distinct()
            .order_by("student__classroom__teacher_id")
        )
        self.assertEqual(
            len(teacher_ids),
            NUM_TEACHERS,
            "Sanity: all seeded teachers should have runs this week",
        )

        for teacher_id in teacher_ids:
            aggregate_weekly_rollups(
                target_week_start, chunk_size=7, teacher_id=teacher_id
            )

        call_command("verify_weekly_rollups", target_week_start.isoformat())

    def test_per_teacher_pass_does_not_wipe_other_teachers_rollups(self):
        """
        Tighter assertion than the verifier-based test: after compacting
        teacher A and then teacher B, teacher A's specific rollup rows
        must still be present unchanged. Guards against a regression
        where _delete_existing_week_rollups stops scoping by teacher_id
        and wipes prior slices.
        """
        from digitmileapi.models import StudentWeekStats

        target_week_start, _ = self.weeks[-1]
        teacher_ids = list(
            Run.objects.filter(
                created_at__date__gte=target_week_start,
                created_at__date__lte=week_end_for(target_week_start),
            )
            .values_list("student__classroom__teacher_id", flat=True)
            .distinct()
            .order_by("student__classroom__teacher_id")
        )
        self.assertGreaterEqual(len(teacher_ids), 2, "Need >=2 teachers")
        teacher_a, teacher_b = teacher_ids[0], teacher_ids[1]

        aggregate_weekly_rollups(target_week_start, teacher_id=teacher_a)
        teacher_a_runs_before = StudentWeekStats.objects.filter(
            week_start=target_week_start, teacher_id=teacher_a
        ).aggregate(total=Sum("runs"))["total"] or 0
        teacher_a_rows_before = StudentWeekStats.objects.filter(
            week_start=target_week_start, teacher_id=teacher_a
        ).count()
        self.assertGreater(
            teacher_a_runs_before, 0,
            "Sanity: teacher A should have aggregated rollups",
        )

        aggregate_weekly_rollups(target_week_start, teacher_id=teacher_b)
        teacher_a_runs_after = StudentWeekStats.objects.filter(
            week_start=target_week_start, teacher_id=teacher_a
        ).aggregate(total=Sum("runs"))["total"] or 0
        teacher_a_rows_after = StudentWeekStats.objects.filter(
            week_start=target_week_start, teacher_id=teacher_a
        ).count()

        self.assertEqual(
            teacher_a_runs_before, teacher_a_runs_after,
            "Teacher A's rollup totals were modified by teacher B's pass",
        )
        self.assertEqual(
            teacher_a_rows_before, teacher_a_rows_after,
            "Teacher A's rollup row count changed during teacher B's pass",
        )

    def test_compact_weekly_runs_end_to_end_whole_week(self):
        """
        Regression test for the bug where verify_weekly_rollups was called
        AFTER the atomic delete block in _compact_slice. Post-delete,
        TurnEvent / SpecialTileTrigger are empty and the verifier reports
        raw=0 vs rollup=N for every field — a structural false positive that
        would fail every compaction in production.

        Exercises the full management command: aggregate → archive → buckets
        → verify → delete. Asserts the run completes (verify must pass
        against the still-present raw rows) and the post-state is what
        compaction promises: rollups populated, raw rows gone,
        WeeklyCompactionRun in COMPACTED.
        """
        target_week_start, target_week_end = self.weeks[-1]
        week_runs = Run.objects.filter(
            created_at__date__gte=target_week_start,
            created_at__date__lte=target_week_end,
        )
        run_count_before = week_runs.count()
        turn_count_before = TurnEvent.objects.filter(run__in=week_runs).count()
        self.assertGreater(run_count_before, 0, "Sanity: seeded runs present")
        self.assertGreater(turn_count_before, 0, "Sanity: seeded turns present")

        with TemporaryDirectory() as archive_root:
            with override_settings(REPLAY_ARCHIVE_ROOT=archive_root):
                call_command(
                    "compact_weekly_runs", target_week_start.isoformat()
                )

        compaction = WeeklyCompactionRun.objects.get(week_start=target_week_start)
        self.assertEqual(
            compaction.status,
            WeeklyCompactionRun.Status.COMPACTED,
            f"Expected COMPACTED, got {compaction.status}",
        )
        self.assertEqual(compaction.run_count, run_count_before)
        self.assertEqual(compaction.turn_rows_deleted, turn_count_before)
        self.assertEqual(
            TurnEvent.objects.filter(run__in=week_runs).count(),
            0,
            "Turn rows should be deleted post-compaction",
        )
        self.assertEqual(
            week_runs.filter(raw_data_compacted_at__isnull=True).count(),
            0,
            "All week runs should be marked raw_data_compacted_at",
        )

    def test_compact_weekly_runs_end_to_end_per_teacher(self):
        """
        Same regression guard as test_compact_weekly_runs_end_to_end_whole_week,
        but for --per-teacher mode where the verifier must be scoped to each
        teacher's slice. Catches the parallel-orchestrator variant of the
        verify-after-delete bug.
        """
        target_week_start, target_week_end = self.weeks[-1]
        week_runs = Run.objects.filter(
            created_at__date__gte=target_week_start,
            created_at__date__lte=target_week_end,
        )
        run_count_before = week_runs.count()
        self.assertGreater(run_count_before, 0)

        with TemporaryDirectory() as archive_root:
            with override_settings(REPLAY_ARCHIVE_ROOT=archive_root):
                call_command(
                    "compact_weekly_runs",
                    target_week_start.isoformat(),
                    "--per-teacher",
                )

        compaction = WeeklyCompactionRun.objects.get(week_start=target_week_start)
        self.assertEqual(compaction.status, WeeklyCompactionRun.Status.COMPACTED)
        self.assertEqual(
            TurnEvent.objects.filter(run__in=week_runs).count(),
            0,
            "Turn rows should be deleted across all per-teacher slices",
        )
        self.assertEqual(
            week_runs.filter(raw_data_compacted_at__isnull=True).count(),
            0,
        )
