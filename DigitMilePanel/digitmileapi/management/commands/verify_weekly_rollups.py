from collections import defaultdict
from datetime import date
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q, Sum

from digitmileapi.analytics import BAG_COMPARATOR_BY_TYPE, parse_card
from digitmileapi.models import (
    ClassroomWeekStats,
    ReplayArchive,
    Run,
    SpecialTileTrigger,
    StudentRunBucketTrend,
    StudentWeekCardFamilyStats,
    StudentWeekCardTypeStats,
    StudentWeekChainLengthStats,
    StudentWeekConditionalStats,
    StudentWeekLevelStats,
    StudentWeekNumberChoiceStats,
    StudentWeekSpecialTileStats,
    StudentWeekStats,
    TurnEvent,
)
from digitmileapi.replay_archives import verify_replay_archive
from digitmileapi.weekly_rollups import (
    clip_decision_time_ms,
    week_end_for,
    week_start_for,
)


logger = logging.getLogger(__name__)


def _card_family(turn):
    if turn["chosen_card_family"] and turn["chosen_card_family"] != "unknown":
        return turn["chosen_card_family"]
    return parse_card(turn["chosen_card"]).get("family", "unknown")


def _card_type(turn):
    if turn["chosen_card_type"] and turn["chosen_card_type"] != "unknown":
        return turn["chosen_card_type"]
    return parse_card(turn["chosen_card"]).get("type", "unknown")


def _card_tile_type(turn):
    return turn["chosen_card_tile_type"] or parse_card(turn["chosen_card"]).get(
        "tile_type"
    )


def _compare_mapping(raw_mapping, rollup_mapping, label, fields):
    failures = []
    for key in sorted(set(raw_mapping.keys()) | set(rollup_mapping.keys())):
        raw_values = raw_mapping.get(key, {})
        rollup_values = rollup_mapping.get(key, {})
        for field in fields:
            raw_value = raw_values.get(field, 0) or 0
            rollup_value = rollup_values.get(field, 0) or 0
            if raw_value != rollup_value:
                failures.append(
                    f"{label} mismatch for {key} field {field}: raw={raw_value} rollup={rollup_value}"
                )
    return failures


class Command(BaseCommand):
    help = "Verify weekly rollup totals against raw gameplay rows"

    def add_arguments(self, parser):
        parser.add_argument("week_start", help="Week start date in YYYY-MM-DD format")
        parser.add_argument(
            "--require-archives",
            action="store_true",
            help="Require READY replay archives with valid checksum for each run",
        )
        parser.add_argument(
            "--verify-run-buckets",
            action="store_true",
            help="Verify historical run-bucket trend coverage for affected student-level pairs",
        )

    def _verify_summary_rollups(self, runs, week_start):
        raw_summary = runs.aggregate(
            runs=Count("id"),
            wins=Count("id", filter=Q(player_won=True)),
            correct_moves=Sum("correct_moves"),
            wrong_moves=Sum("wrong_moves"),
        )
        rollup_summary = StudentWeekStats.objects.filter(
            week_start=week_start
        ).aggregate(
            runs=Sum("runs"),
            wins=Sum("wins"),
            correct_moves=Sum("correct_moves"),
            wrong_moves=Sum("wrong_moves"),
        )

        failures = []
        for key in ["runs", "wins", "correct_moves", "wrong_moves"]:
            if (raw_summary.get(key) or 0) != (rollup_summary.get(key) or 0):
                failures.append(
                    f"summary mismatch for {key}: raw={(raw_summary.get(key) or 0)} rollup={(rollup_summary.get(key) or 0)}"
                )

        raw_turn_count = TurnEvent.objects.filter(run__in=runs).count()
        raw_trigger_count = SpecialTileTrigger.objects.filter(
            turn__run__in=runs
        ).count()
        chain_rollup_count = (
            StudentWeekChainLengthStats.objects.filter(week_start=week_start).aggregate(
                total=Sum("turn_count")
            )["total"]
            or 0
        )
        trigger_rollup_count = (
            StudentWeekSpecialTileStats.objects.filter(week_start=week_start).aggregate(
                total=Sum("trigger_count")
            )["total"]
            or 0
        )
        level_rollup_count = (
            StudentWeekLevelStats.objects.filter(week_start=week_start).aggregate(
                total=Sum("runs")
            )["total"]
            or 0
        )
        classroom_rollup_count = (
            ClassroomWeekStats.objects.filter(week_start=week_start).aggregate(
                total=Sum("runs")
            )["total"]
            or 0
        )

        if raw_turn_count != chain_rollup_count:
            failures.append(
                f"turn count mismatch: raw={raw_turn_count} rollup={chain_rollup_count}"
            )
        if raw_trigger_count != trigger_rollup_count:
            failures.append(
                f"trigger count mismatch: raw={raw_trigger_count} rollup={trigger_rollup_count}"
            )
        if (raw_summary.get("runs") or 0) != level_rollup_count:
            failures.append(
                f"level rollup run mismatch: raw={raw_summary.get('runs') or 0} rollup={level_rollup_count}"
            )
        if (raw_summary.get("runs") or 0) != classroom_rollup_count:
            failures.append(
                f"classroom rollup run mismatch: raw={raw_summary.get('runs') or 0} rollup={classroom_rollup_count}"
            )

        return failures

    def _verify_card_family_rollups(self, runs, week_start):
        raw = defaultdict(lambda: {"offered": 0, "chosen": 0, "correct": 0, "wrong": 0})
        for turn in TurnEvent.objects.filter(run__in=runs).values(
            "run__level",
            "chosen_card_family",
            "chosen_card",
            "offered_cards",
            "was_correct",
        ):
            family = _card_family(turn)
            key = (turn["run__level"], family)
            raw[key]["chosen"] += 1
            raw[key]["correct"] += 1 if turn["was_correct"] else 0
            raw[key]["wrong"] += 0 if turn["was_correct"] else 1
            for offered_card in turn["offered_cards"] or []:
                offered_family = parse_card(offered_card).get("family", "unknown")
                raw[(turn["run__level"], offered_family)]["offered"] += 1

        rollup = {}
        for row in (
            StudentWeekCardFamilyStats.objects.filter(week_start=week_start)
            .values("level", "card_family")
            .annotate(
                offered=Sum("offered_count"),
                chosen=Sum("chosen_count"),
                correct=Sum("correct_count"),
                wrong=Sum("wrong_count"),
            )
        ):
            rollup[(row["level"], row["card_family"])] = {
                "offered": row["offered"] or 0,
                "chosen": row["chosen"] or 0,
                "correct": row["correct"] or 0,
                "wrong": row["wrong"] or 0,
            }

        return _compare_mapping(
            raw, rollup, "card family", ["offered", "chosen", "correct", "wrong"]
        )

    def _verify_card_type_rollups(self, runs, week_start):
        raw = defaultdict(
            lambda: {
                "chosen_count": 0,
                "decision_time_sum_ms": 0,
                "decision_time_count": 0,
                "clipped_decision_time_sum_ms": 0,
                "outlier_count": 0,
            }
        )
        for turn in TurnEvent.objects.filter(run__in=runs).values(
            "run__level",
            "chosen_card_type",
            "chosen_card",
            "card_decision_time_ms",
        ):
            card_type = _card_type(turn)
            key = (turn["run__level"], card_type)
            decision_time = turn["card_decision_time_ms"] or 0
            clipped_value, was_clipped = clip_decision_time_ms(decision_time)
            raw[key]["chosen_count"] += 1
            raw[key]["decision_time_sum_ms"] += decision_time
            raw[key]["decision_time_count"] += 1
            raw[key]["clipped_decision_time_sum_ms"] += clipped_value
            raw[key]["outlier_count"] += 1 if was_clipped else 0

        rollup = {}
        for row in (
            StudentWeekCardTypeStats.objects.filter(week_start=week_start)
            .values("level", "card_type")
            .annotate(
                chosen_count=Sum("chosen_count"),
                decision_time_sum_ms=Sum("decision_time_sum_ms"),
                decision_time_count=Sum("decision_time_count"),
                clipped_decision_time_sum_ms=Sum("clipped_decision_time_sum_ms"),
                outlier_count=Sum("outlier_count"),
            )
        ):
            rollup[(row["level"], row["card_type"])] = {
                "chosen_count": row["chosen_count"] or 0,
                "decision_time_sum_ms": row["decision_time_sum_ms"] or 0,
                "decision_time_count": row["decision_time_count"] or 0,
                "clipped_decision_time_sum_ms": row["clipped_decision_time_sum_ms"]
                or 0,
                "outlier_count": row["outlier_count"] or 0,
            }

        return _compare_mapping(
            raw,
            rollup,
            "card type",
            [
                "chosen_count",
                "decision_time_sum_ms",
                "decision_time_count",
                "clipped_decision_time_sum_ms",
                "outlier_count",
            ],
        )

    def _verify_number_choice_rollups(self, runs, week_start):
        raw = defaultdict(
            lambda: {
                "choice_count": 0,
                "decision_time_sum_ms": 0,
                "decision_time_count": 0,
            }
        )
        for turn in TurnEvent.objects.filter(
            run__in=runs,
            chosen_number__isnull=False,
        ).values("run__level", "chosen_number", "number_decision_time_ms"):
            key = (turn["run__level"], turn["chosen_number"])
            raw[key]["choice_count"] += 1
            raw[key]["decision_time_sum_ms"] += turn["number_decision_time_ms"] or 0
            raw[key]["decision_time_count"] += 1

        rollup = {}
        for row in (
            StudentWeekNumberChoiceStats.objects.filter(week_start=week_start)
            .values("level", "chosen_number")
            .annotate(
                choice_count=Sum("choice_count"),
                decision_time_sum_ms=Sum("decision_time_sum_ms"),
                decision_time_count=Sum("decision_time_count"),
            )
        ):
            rollup[(row["level"], row["chosen_number"])] = {
                "choice_count": row["choice_count"] or 0,
                "decision_time_sum_ms": row["decision_time_sum_ms"] or 0,
                "decision_time_count": row["decision_time_count"] or 0,
            }

        return _compare_mapping(
            raw,
            rollup,
            "number choice",
            ["choice_count", "decision_time_sum_ms", "decision_time_count"],
        )

    def _verify_conditional_rollups(self, runs, week_start):
        raw = defaultdict(
            lambda: {"total_count": 0, "correct_count": 0, "else_count": 0}
        )

        for turn in TurnEvent.objects.filter(
            run__in=runs, chosen_card_family="conditional_tile"
        ).values(
            "run__level",
            "chosen_card_tile_type",
            "chosen_card",
            "was_correct",
            "tile_before_type",
        ):
            tile_type = _card_tile_type(turn)
            if tile_type is None:
                continue
            key = (
                turn["run__level"],
                StudentWeekConditionalStats.ConditionalKind.TILE,
                str(tile_type),
            )
            raw[key]["total_count"] += 1
            raw[key]["correct_count"] += 1 if turn["was_correct"] else 0
            raw[key]["else_count"] += 1 if turn["tile_before_type"] != tile_type else 0

        bag_turns = (
            TurnEvent.objects.filter(
                run__in=runs,
                chosen_card_family__in=[
                    "conditional_bag_eq",
                    "conditional_bag_lt",
                    "conditional_bag_gt",
                ],
            )
            .values(
                "run_id",
                "run__level",
                "turn_index",
                "chosen_card_type",
                "chosen_card",
                "was_correct",
                "chosen_number",
            )
            .order_by("run_id", "turn_index")
        )

        current_run_id = None
        bag_number = 1
        for turn in bag_turns:
            if turn["run_id"] != current_run_id:
                current_run_id = turn["run_id"]
                bag_number = 1

            comparator = BAG_COMPARATOR_BY_TYPE.get(turn["chosen_card_type"])
            threshold = parse_card(turn["chosen_card"]).get("if_value")
            if comparator is None or threshold is None:
                if turn["chosen_number"] is not None:
                    bag_number = turn["chosen_number"]
                continue

            key = (
                turn["run__level"],
                StudentWeekConditionalStats.ConditionalKind.BAG,
                comparator,
            )
            raw[key]["total_count"] += 1
            raw[key]["correct_count"] += 1 if turn["was_correct"] else 0
            if comparator == "eq":
                condition_met = bag_number == threshold
            elif comparator == "lt":
                condition_met = bag_number < threshold
            else:
                condition_met = bag_number > threshold
            raw[key]["else_count"] += 0 if condition_met else 1

            if turn["chosen_number"] is not None:
                bag_number = turn["chosen_number"]

        rollup = {}
        for row in (
            StudentWeekConditionalStats.objects.filter(week_start=week_start)
            .values("level", "conditional_kind", "bucket_key")
            .annotate(
                total_count=Sum("total_count"),
                correct_count=Sum("correct_count"),
                else_count=Sum("else_count"),
            )
        ):
            rollup[(row["level"], row["conditional_kind"], row["bucket_key"])] = {
                "total_count": row["total_count"] or 0,
                "correct_count": row["correct_count"] or 0,
                "else_count": row["else_count"] or 0,
            }

        return _compare_mapping(
            raw,
            rollup,
            "conditional",
            ["total_count", "correct_count", "else_count"],
        )

    def _verify_archives(self, runs):
        failures = []
        for run in runs:
            archive = getattr(run, "replay_archive", None)
            if archive is None:
                failures.append(f"missing replay archive for run {run.id}")
                continue
            if archive.archive_status != ReplayArchive.ArchiveStatus.READY:
                failures.append(
                    f"archive not ready for run {run.id}: status={archive.archive_status}"
                )
            if not archive.storage_path or not archive.checksum_sha256:
                failures.append(
                    f"archive metadata incomplete for run {run.id}: storage_path/checksum missing"
                )
                continue
            if not verify_replay_archive(archive):
                failures.append(
                    f"archive checksum verification failed for run {run.id}: {archive.verification_error}"
                )
        return failures

    def _verify_run_buckets(self, runs):
        failures = []
        week_run_ids = list(runs.values_list("id", flat=True))
        affected_pairs = set(runs.values_list("student_id", "level"))
        for student_id, level in affected_pairs:
            run_scope = Run.objects.filter(student_id=student_id, level=level).filter(
                Q(raw_data_compacted_at__isnull=False) | Q(id__in=week_run_ids)
            )
            raw_totals = run_scope.aggregate(
                run_count=Count("id"),
                wins=Count("id", filter=Q(player_won=True)),
                correct_moves=Sum("correct_moves"),
                wrong_moves=Sum("wrong_moves"),
                score_sum=Sum("score"),
                score_count=Count("id"),
                elapsed_sum_ms=Sum("elapsed_ms"),
                elapsed_count=Count("id"),
            )
            trend_totals = StudentRunBucketTrend.objects.filter(
                student_id=student_id,
                level=level,
            ).aggregate(
                run_count=Sum("run_count"),
                wins=Sum("wins"),
                correct_moves=Sum("correct_moves"),
                wrong_moves=Sum("wrong_moves"),
                score_sum=Sum("score_sum"),
                score_count=Sum("score_count"),
                elapsed_sum_ms=Sum("elapsed_sum_ms"),
                elapsed_count=Sum("elapsed_count"),
            )

            for field in [
                "run_count",
                "wins",
                "correct_moves",
                "wrong_moves",
                "score_sum",
                "score_count",
                "elapsed_sum_ms",
                "elapsed_count",
            ]:
                if (raw_totals.get(field) or 0) != (trend_totals.get(field) or 0):
                    failures.append(
                        f"run bucket mismatch for student={student_id} level={level} field {field}: raw={(raw_totals.get(field) or 0)} rollup={(trend_totals.get(field) or 0)}"
                    )

        return failures

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
        ).select_related("replay_archive")
        if not runs.exists():
            raise CommandError("No runs found for requested week")

        failures = []
        failures.extend(self._verify_summary_rollups(runs, week_start))
        failures.extend(self._verify_card_family_rollups(runs, week_start))
        failures.extend(self._verify_card_type_rollups(runs, week_start))
        failures.extend(self._verify_conditional_rollups(runs, week_start))
        failures.extend(self._verify_number_choice_rollups(runs, week_start))

        if options["require_archives"]:
            failures.extend(self._verify_archives(runs))
        if options["verify_run_buckets"]:
            failures.extend(self._verify_run_buckets(runs))

        if failures:
            logger.error(
                "weekly_rollup_verification_failed %s",
                {
                    "week_start": str(week_start),
                    "week_end": str(week_end),
                    "failures": failures,
                },
            )
            raise CommandError("; ".join(failures))

        logger.info(
            "weekly_rollup_verification_succeeded %s",
            {
                "week_start": str(week_start),
                "week_end": str(week_end),
                "require_archives": options["require_archives"],
                "verify_run_buckets": options["verify_run_buckets"],
            },
        )
        self.stdout.write(self.style.SUCCESS("Weekly rollups verified successfully"))
