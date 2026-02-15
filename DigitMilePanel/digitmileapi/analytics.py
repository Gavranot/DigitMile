"""
Query helper functions for run analytics.
Provides aggregated statistics for teachers and administrators.
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from django.conf import settings
from django.db.models import Avg, Count, Sum, F, Q, FloatField, Min, Max, StdDev
from django.db.models.functions import Cast
from .models import Run, TurnEvent, Student, SpecialTileTrigger


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

BAG_COMPARATOR_BY_TYPE = {
    "IfBagEqualXMoveYElseMoveZ": "eq",
    "IfBagLessXMoveYElseMoveZ": "lt",
    "IfBagGreaterXMoveYElseMoveZ": "gt",
}

CARD_FAMILY_BY_NAME = {
    "move": "move",
    "conditional_tile": "conditional_tile",
    "bagcount": "bagcount",
    "back": "back",
    "foreach_tile": "foreach_tile",
}


def _parse_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_card_data(card_data_str):
    fields = {
        "tile_type": None,
        "if_sign": None,
        "if_value": None,
        "then_value": None,
        "else_value": None,
    }

    if not card_data_str:
        return fields

    raw = str(card_data_str).strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1].strip()
    if raw.lower().startswith("carddata:"):
        raw = raw.split(":", 1)[1].strip()

    for key, value in re.findall(r"(\w+)\s*=\s*([^,]*)", raw):
        normalized_key = key.strip()
        normalized_value = value.strip()

        if normalized_value == "":
            parsed_value = None
        elif normalized_key == "ifSign":
            parsed_value = normalized_value
        else:
            parsed_value = _parse_int(normalized_value)

        if normalized_key == "tileType":
            fields["tile_type"] = parsed_value
        elif normalized_key == "ifSign":
            fields["if_sign"] = parsed_value
        elif normalized_key == "ifValue":
            fields["if_value"] = parsed_value
        elif normalized_key == "thenValue":
            fields["then_value"] = parsed_value
        elif normalized_key == "elseValue":
            fields["else_value"] = parsed_value

    return fields


def normalize_card_type(card_type):
    if card_type in {"Bug", "Back"}:
        return "Back"
    if isinstance(card_type, str) and card_type.startswith("AllBack"):
        return "Back"
    return card_type


def parse_card(card_data):
    if not isinstance(card_data, dict):
        return {
            "type": "unknown",
            "family": "unknown",
            "tile_type": None,
            "if_sign": None,
            "if_value": None,
            "then_value": None,
            "else_value": None,
        }

    raw_type = card_data.get("type") or "unknown"
    normalized_type = normalize_card_type(raw_type)
    parsed = parse_card_data(card_data.get("data"))

    if normalized_type in {"Back", "MoveX"} and parsed["then_value"] is None:
        parsed["then_value"] = 1

    return {
        "type": normalized_type,
        "family": CARD_FAMILY_BY_TYPE.get(normalized_type, "unknown"),
        **parsed,
    }


def card_family_from_name(card_name):
    if not card_name:
        return "unknown"

    name = str(card_name)
    if name.startswith("AllBack") or name.startswith("Back") or name == "Bug":
        return "back"
    if name.startswith("Bag") or name in {"CardCountBag", "BagMove"}:
        return "bagcount"
    if name.startswith("For"):
        return "foreach_tile"
    if name.startswith("Move") and "Else" in name:
        return "conditional_tile"
    if name.startswith("Move"):
        return "move"
    return "unknown"


def _deck_assets_dir():
    base_dir = Path(settings.BASE_DIR)
    return base_dir / "digitmileapi" / "templates" / "assets"


def load_level_deck(level):
    deck_filename = f"Level{level}.json"
    deck_path = _deck_assets_dir() / deck_filename
    if not deck_path.exists():
        # Backward compatibility with older repo layout.
        legacy_path = Path(settings.BASE_DIR).parent / "DigitMile" / "assets" / deck_filename
        if not legacy_path.exists():
            return None
        deck_path = legacy_path

    with deck_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    counts = defaultdict(int)
    for entry in data.get("cards", []):
        card_name = entry.get("cardName")
        count = entry.get("count", 0)
        if card_name:
            counts[card_name] += int(count or 0)

    return {
        "level": level,
        "number_cards_in_deck": bool(data.get("NumberCardsInDeck")),
        "counts": counts,
    }


def _iter_turns_with_bag_number(turns):
    current_run_id = None
    bag_number = 1

    for turn in turns:
        run_id = turn.get("run_id")
        if run_id != current_run_id:
            current_run_id = run_id
            bag_number = 1

        bag_number_before = bag_number

        chosen_number = turn.get("chosen_number")
        if chosen_number == -1:
            chosen_number = None

        if chosen_number is not None:
            bag_number = chosen_number

        yield turn, bag_number_before


def _get_tile_type_from_map(game_map, tile_index):
    if not game_map:
        return None
    if tile_index is None:
        return None

    for tile in game_map:
        if not isinstance(tile, dict):
            continue
        if tile.get("tileMapIndex") == tile_index:
            return tile.get("tileType", tile.get("tileIndex"))
    return None


def _summary_stats(values):
    if not values:
        return None
    sorted_values = sorted(values)
    count = len(sorted_values)
    return {
        "count": count,
        "avg": sum(sorted_values) / count,
        "min": sorted_values[0],
        "max": sorted_values[-1],
        "median": sorted_values[count // 2],
        "q1": sorted_values[count // 4] if count >= 4 else sorted_values[0],
        "q3": sorted_values[3 * count // 4] if count >= 4 else sorted_values[-1],
    }


class RunAnalytics:
    """Analytics queries for Run data."""

    @staticmethod
    def win_rate_by_level(teacher=None, classroom_id=None, student_ids=None):
        """
        Calculate win rate by level for a given scope.

        Args:
            teacher: Teacher model instance to filter by
            classroom_id: Classroom ID to filter by
            student_ids: List of student IDs to filter by

        Returns:
            QuerySet with level, total_runs, wins, win_rate
        """
        queryset = Run.objects.all()

        if student_ids:
            queryset = queryset.filter(student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(student__classroom__teacher=teacher)

        return (
            queryset.values("level")
            .annotate(
                total_runs=Count("id"),
                wins=Count("id", filter=Q(player_won=True)),
            )
            .annotate(
                win_rate=Cast(F("wins"), FloatField())
                * 100.0
                / Cast(F("total_runs"), FloatField())
            )
            .order_by("level")
        )

    @staticmethod
    def avg_score_by_level(teacher=None, classroom_id=None, student_ids=None):
        """
        Calculate average score by level for a given scope.

        Args:
            teacher: Teacher model instance to filter by
            classroom_id: Classroom ID to filter by
            student_ids: List of student IDs to filter by

        Returns:
            QuerySet with level, avg_score, min_score, max_score, total_runs
        """
        queryset = Run.objects.all()

        if student_ids:
            queryset = queryset.filter(student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(student__classroom__teacher=teacher)

        return (
            queryset.values("level")
            .annotate(
                avg_score=Avg("score"),
                min_score=Min("score"),
                max_score=Max("score"),
                total_runs=Count("id"),
            )
            .order_by("level")
        )

    @staticmethod
    def avg_card_decision_time_by_level(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Calculate average card decision time by level.

        Args:
            teacher: Teacher model instance to filter by
            classroom_id: Classroom ID to filter by
            student_ids: List of student IDs to filter by

        Returns:
            QuerySet with level, avg_decision_time_ms, total_turns
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        return (
            queryset.values("run__level")
            .annotate(
                avg_decision_time_ms=Avg("card_decision_time_ms"),
                total_turns=Count("id"),
            )
            .order_by("run__level")
        )

    @staticmethod
    def wrong_moves_rate_by_level(teacher=None, classroom_id=None, student_ids=None):
        """
        Calculate wrong moves rate by level.

        Args:
            teacher: Teacher model instance to filter by
            classroom_id: Classroom ID to filter by
            student_ids: List of student IDs to filter by

        Returns:
            QuerySet with level, total_correct, total_wrong, total_moves, wrong_rate
        """
        queryset = Run.objects.all()

        if student_ids:
            queryset = queryset.filter(student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(student__classroom__teacher=teacher)

        return (
            queryset.values("level")
            .annotate(
                total_correct=Sum("correct_moves"),
                total_wrong=Sum("wrong_moves"),
            )
            .annotate(
                total_moves=F("total_correct") + F("total_wrong"),
                wrong_rate=Cast(F("total_wrong"), FloatField())
                * 100.0
                / (
                    Cast(F("total_correct"), FloatField())
                    + Cast(F("total_wrong"), FloatField())
                ),
            )
            .order_by("level")
        )

    @staticmethod
    def student_performance_summary(student_id):
        """
        Get comprehensive performance summary for a single student.

        Args:
            student_id: The student ID to get metrics for

        Returns:
            dict with various performance metrics, or None if no runs exist
        """
        runs = Run.objects.filter(student_id=student_id)

        if not runs.exists():
            return None

        total_runs = runs.count()
        wins = runs.filter(player_won=True).count()

        agg = runs.aggregate(
            avg_score=Avg("score"),
            total_correct=Sum("correct_moves"),
            total_wrong=Sum("wrong_moves"),
            avg_elapsed=Avg("elapsed_ms"),
        )

        turn_agg = TurnEvent.objects.filter(run__student_id=student_id).aggregate(
            avg_card_decision=Avg("card_decision_time_ms"),
            avg_number_decision=Avg("number_decision_time_ms"),
        )

        total_moves = (agg["total_correct"] or 0) + (agg["total_wrong"] or 0)
        accuracy = (
            ((agg["total_correct"] or 0) / total_moves * 100) if total_moves > 0 else 0
        )

        return {
            "total_runs": total_runs,
            "wins": wins,
            "win_rate": (wins / total_runs * 100) if total_runs > 0 else 0,
            "avg_score": agg["avg_score"] or 0,
            "accuracy": accuracy,
            "avg_elapsed_ms": agg["avg_elapsed"] or 0,
            "avg_card_decision_ms": turn_agg["avg_card_decision"] or 0,
            "avg_number_decision_ms": turn_agg["avg_number_decision"],
        }

    @staticmethod
    def classroom_leaderboard(classroom_id, metric="win_rate", limit=10):
        """
        Get top students in a classroom by specified metric.

        Args:
            classroom_id: Classroom to analyze
            metric: One of 'win_rate', 'avg_score', 'accuracy', 'total_runs'
            limit: Number of students to return

        Returns:
            List of dicts with student info and metric values
        """
        students = Student.objects.filter(classroom_id=classroom_id)

        results = []
        for student in students:
            runs = Run.objects.filter(student=student)
            if not runs.exists():
                continue

            total_runs = runs.count()
            wins = runs.filter(player_won=True).count()
            agg = runs.aggregate(
                avg_score=Avg("score"),
                total_correct=Sum("correct_moves"),
                total_wrong=Sum("wrong_moves"),
            )

            total_moves = (agg["total_correct"] or 0) + (agg["total_wrong"] or 0)

            student_data = {
                "student_id": student.id,
                "student_name": student.full_name,
                "total_runs": total_runs,
                "win_rate": (wins / total_runs * 100) if total_runs > 0 else 0,
                "avg_score": agg["avg_score"] or 0,
                "accuracy": ((agg["total_correct"] or 0) / total_moves * 100)
                if total_moves > 0
                else 0,
            }
            results.append(student_data)

        reverse = metric != "wrong_rate"
        results.sort(key=lambda x: x.get(metric, 0), reverse=reverse)

        return results[:limit]

    @staticmethod
    def time_distribution_by_level(teacher=None, classroom_id=None, student_ids=None):
        """
        Get elapsed time statistics by level for box plot visualization.

        Args:
            teacher: Teacher model instance to filter by
            classroom_id: Classroom ID to filter by
            student_ids: List of student IDs to filter by

        Returns:
            QuerySet with level, avg_time_ms, min_time_ms, max_time_ms, std_time_ms, run_count
        """
        queryset = Run.objects.all()

        if student_ids:
            queryset = queryset.filter(student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(student__classroom__teacher=teacher)

        return (
            queryset.values("level")
            .annotate(
                avg_time_ms=Avg("elapsed_ms"),
                min_time_ms=Min("elapsed_ms"),
                max_time_ms=Max("elapsed_ms"),
                std_time_ms=StdDev("elapsed_ms"),
                run_count=Count("id"),
            )
            .order_by("level")
        )

    @staticmethod
    def speed_vs_accuracy_scatter(
        teacher=None, classroom_id=None, student_ids=None, limit=1000
    ):
        """
        Get per-run speed and accuracy data for scatter plot.

        Args:
            teacher: Teacher model instance to filter by
            classroom_id: Classroom ID to filter by
            student_ids: List of student IDs to filter by
            limit: Maximum number of data points to return

        Returns:
            List of dicts with x (elapsed_seconds), y (accuracy), level, student
        """
        queryset = Run.objects.all()

        if student_ids:
            queryset = queryset.filter(student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(student__classroom__teacher=teacher)

        runs = queryset.select_related("student").values(
            "elapsed_ms", "correct_moves", "wrong_moves", "level", "student__full_name"
        )[:limit]

        scatter_data = []
        for run in runs:
            total_moves = (run["correct_moves"] or 0) + (run["wrong_moves"] or 0)
            if total_moves > 0:
                accuracy = (run["correct_moves"] or 0) / total_moves * 100
                scatter_data.append(
                    {
                        "x": (run["elapsed_ms"] or 0) / 1000,  # Convert to seconds
                        "y": accuracy,
                        "level": run["level"],
                        "student": run["student__full_name"],
                    }
                )

        return scatter_data

    @staticmethod
    def mistake_hotspots_by_level(teacher=None, classroom_id=None, student_ids=None):
        """
        Get mistake locations grouped by level and tile position for heatmap.

        Args:
            teacher: Teacher model instance to filter by
            classroom_id: Classroom ID to filter by
            student_ids: List of student IDs to filter by

        Returns:
            Dict mapping level -> {tile_index: mistake_count}
        """
        queryset = TurnEvent.objects.filter(was_correct=False)

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        hotspots = (
            queryset.values("tile_before_index", "run__level")
            .annotate(mistake_count=Count("id"))
            .order_by("run__level", "-mistake_count")
        )

        level_hotspots = {}
        for entry in hotspots:
            level = entry["run__level"]
            if level not in level_hotspots:
                level_hotspots[level] = {}
            level_hotspots[level][entry["tile_before_index"]] = entry["mistake_count"]

        return level_hotspots

    @staticmethod
    def special_tile_breakdown(teacher=None, classroom_id=None, student_ids=None):
        """
        Get skateboard (type 5) vs clown (type 4) trigger counts by level.

        Args:
            teacher: Teacher model instance to filter by
            classroom_id: Classroom ID to filter by
            student_ids: List of student IDs to filter by

        Returns:
            QuerySet with turn__run__level, special_tile_type, trigger_count
        """
        queryset = SpecialTileTrigger.objects.all()

        if student_ids:
            queryset = queryset.filter(turn__run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(turn__run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(turn__run__student__classroom__teacher=teacher)

        return (
            queryset.values("turn__run__level", "special_tile_type")
            .annotate(trigger_count=Count("id"))
            .order_by("turn__run__level", "special_tile_type")
        )

    @staticmethod
    def decision_time_by_card_type(teacher=None, classroom_id=None, student_ids=None):
        """
        Get decision time statistics grouped by card type.

        Args:
            teacher: Teacher model instance to filter by
            classroom_id: Classroom ID to filter by
            student_ids: List of student IDs to filter by

        Returns:
            Dict mapping card_type -> {count, avg, min, max, median, q1, q3}
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values("chosen_card", "card_decision_time_ms")

        card_type_times = defaultdict(list)
        for turn in turns:
            chosen_card = turn.get("chosen_card")
            parsed_card = parse_card(chosen_card)
            card_type = parsed_card.get("type", "unknown")
            if turn["card_decision_time_ms"] is not None:
                card_type_times[card_type].append(turn["card_decision_time_ms"])

        # Calculate statistics for each card type
        result = {}
        for card_type, times in card_type_times.items():
            if times:
                times_sorted = sorted(times)
                n = len(times_sorted)
                result[card_type] = {
                    "count": n,
                    "avg": sum(times) / n,
                    "min": times_sorted[0],
                    "max": times_sorted[-1],
                    "median": times_sorted[n // 2],
                    "q1": times_sorted[n // 4] if n >= 4 else times_sorted[0],
                    "q3": times_sorted[3 * n // 4] if n >= 4 else times_sorted[-1],
                }

        return result

    @staticmethod
    def deck_expected_share_by_family():
        """
        Expected family share per level based on deck composition.

        Returns:
            List of dicts with level, family, expected_share, total_cards, number_cards_in_deck
        """
        results = []
        for level in range(1, 7):
            deck = load_level_deck(level)
            if not deck:
                continue

            family_counts = defaultdict(int)
            total_cards = 0

            for card_name, count in deck["counts"].items():
                family = card_family_from_name(card_name)
                family_counts[family] += count
                total_cards += count

            for family, count in family_counts.items():
                results.append(
                    {
                        "level": level,
                        "family": family,
                        "expected_share": (count / total_cards * 100)
                        if total_cards > 0
                        else 0,
                        "total_cards": total_cards,
                        "number_cards_in_deck": deck["number_cards_in_deck"],
                    }
                )

        return results

    @staticmethod
    def offer_choice_share_by_family(teacher=None, classroom_id=None, student_ids=None):
        """
        Offer vs choice share per family by level.

        Returns:
            List of dicts with level, family, offered, chosen, offered_share, chosen_share, choice_rate
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values("run__level", "chosen_card", "offered_cards")

        offered_counts = defaultdict(int)
        chosen_counts = defaultdict(int)
        offered_totals = defaultdict(int)
        chosen_totals = defaultdict(int)

        for turn in turns:
            level = turn.get("run__level")
            chosen_card = parse_card(turn.get("chosen_card"))
            chosen_counts[(level, chosen_card["family"])] += 1
            chosen_totals[level] += 1

            offered_cards = turn.get("offered_cards") or []
            for card in offered_cards:
                offered_card = parse_card(card)
                offered_counts[(level, offered_card["family"])] += 1
                offered_totals[level] += 1

        families = set(
            [key[1] for key in offered_counts.keys()]
            + [key[1] for key in chosen_counts.keys()]
        )
        results = []
        for level in sorted(
            set(list(offered_totals.keys()) + list(chosen_totals.keys()))
        ):
            total_offered = offered_totals.get(level, 0)
            total_chosen = chosen_totals.get(level, 0)
            for family in families:
                offered = offered_counts.get((level, family), 0)
                chosen = chosen_counts.get((level, family), 0)
                results.append(
                    {
                        "level": level,
                        "family": family,
                        "offered": offered,
                        "chosen": chosen,
                        "offered_share": (offered / total_offered * 100)
                        if total_offered > 0
                        else 0,
                        "chosen_share": (chosen / total_chosen * 100)
                        if total_chosen > 0
                        else 0,
                        "choice_rate": (chosen / offered * 100) if offered > 0 else 0,
                    }
                )

        return results

    @staticmethod
    def card_accuracy_by_family_by_level(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Accuracy rates grouped by card family and level.

        Returns:
            List of dicts with level, family, total, correct, wrong, accuracy
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values("run__level", "chosen_card", "was_correct")

        counts = defaultdict(lambda: {"total": 0, "correct": 0})
        for turn in turns:
            level = turn.get("run__level")
            card = parse_card(turn.get("chosen_card"))
            family = card["family"]
            counts[(level, family)]["total"] += 1
            if turn.get("was_correct"):
                counts[(level, family)]["correct"] += 1

        results = []
        for (level, family), values in counts.items():
            total = values["total"]
            correct = values["correct"]
            results.append(
                {
                    "level": level,
                    "family": family,
                    "total": total,
                    "correct": correct,
                    "wrong": total - correct,
                    "accuracy": (correct / total * 100) if total > 0 else 0,
                }
            )

        return results

    @staticmethod
    def decision_time_by_family_by_level(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Decision time stats grouped by card family and level.

        Returns:
            List of dicts with level, family, stats
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values("run__level", "chosen_card", "card_decision_time_ms")

        family_times = defaultdict(list)
        for turn in turns:
            level = turn.get("run__level")
            card = parse_card(turn.get("chosen_card"))
            decision_time = turn.get("card_decision_time_ms")
            if decision_time is not None:
                family_times[(level, card["family"])].append(decision_time)

        results = []
        for (level, family), times in family_times.items():
            stats = _summary_stats(times)
            if stats:
                results.append({"level": level, "family": family, **stats})

        return results

    @staticmethod
    def tile_conditional_accuracy_by_tile_type_by_level(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Accuracy for tile-conditional cards by tileType and level.

        Returns:
            Dict with by_tile_type list and else_rate_by_level
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values(
            "run__level",
            "chosen_card",
            "was_correct",
            "tile_before_type",
        )

        counts = defaultdict(lambda: {"total": 0, "correct": 0, "else_count": 0})
        total_else_by_level = defaultdict(int)
        total_conditional_by_level = defaultdict(int)

        for turn in turns:
            card = parse_card(turn.get("chosen_card"))
            if card["family"] != "conditional_tile":
                continue
            tile_type = card["tile_type"]
            if tile_type is None:
                continue

            level = turn.get("run__level")
            total_conditional_by_level[level] += 1
            counts[(level, tile_type)]["total"] += 1
            if turn.get("was_correct"):
                counts[(level, tile_type)]["correct"] += 1

            if turn.get("tile_before_type") != tile_type:
                counts[(level, tile_type)]["else_count"] += 1
                total_else_by_level[level] += 1

        by_tile_type = []
        for (level, tile_type), values in counts.items():
            total = values["total"]
            correct = values["correct"]
            else_count = values["else_count"]
            by_tile_type.append(
                {
                    "level": level,
                    "tile_type": tile_type,
                    "total": total,
                    "correct": correct,
                    "accuracy": (correct / total * 100) if total > 0 else 0,
                    "else_rate": (else_count / total * 100) if total > 0 else 0,
                }
            )

        else_rate_by_level = []
        for level, total_conditional in total_conditional_by_level.items():
            total_else = total_else_by_level.get(level, 0)
            else_rate_by_level.append(
                {
                    "level": level,
                    "else_rate": (total_else / total_conditional * 100)
                    if total_conditional > 0
                    else 0,
                }
            )

        return {
            "by_tile_type": by_tile_type,
            "else_rate_by_level": else_rate_by_level,
        }

    @staticmethod
    def bag_conditional_accuracy_by_comparator_by_level(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Accuracy for bag-conditional cards by comparator and level.

        Returns:
            Dict with by_comparator list and else_rate_by_level
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values(
            "run_id",
            "run__level",
            "turn_index",
            "chosen_card",
            "was_correct",
            "chosen_number",
        ).order_by("run_id", "turn_index")

        counts = defaultdict(lambda: {"total": 0, "correct": 0, "else_count": 0})
        total_else_by_level = defaultdict(int)
        total_conditional_by_level = defaultdict(int)

        for turn, bag_number in _iter_turns_with_bag_number(turns):
            card = parse_card(turn.get("chosen_card"))
            comparator = BAG_COMPARATOR_BY_TYPE.get(card["type"])
            if not comparator:
                continue

            threshold = card["if_value"]
            if threshold is None or bag_number is None:
                continue

            level = turn.get("run__level")
            total_conditional_by_level[level] += 1
            counts[(level, comparator)]["total"] += 1
            if turn.get("was_correct"):
                counts[(level, comparator)]["correct"] += 1

            if comparator == "eq":
                condition_met = bag_number == threshold
            elif comparator == "lt":
                condition_met = bag_number < threshold
            else:
                condition_met = bag_number > threshold

            if not condition_met:
                counts[(level, comparator)]["else_count"] += 1
                total_else_by_level[level] += 1

        by_comparator = []
        for (level, comparator), values in counts.items():
            total = values["total"]
            correct = values["correct"]
            else_count = values["else_count"]
            by_comparator.append(
                {
                    "level": level,
                    "comparator": comparator,
                    "total": total,
                    "correct": correct,
                    "accuracy": (correct / total * 100) if total > 0 else 0,
                    "else_rate": (else_count / total * 100) if total > 0 else 0,
                }
            )

        else_rate_by_level = []
        for level, total_conditional in total_conditional_by_level.items():
            total_else = total_else_by_level.get(level, 0)
            else_rate_by_level.append(
                {
                    "level": level,
                    "else_rate": (total_else / total_conditional * 100)
                    if total_conditional > 0
                    else 0,
                }
            )

        return {
            "by_comparator": by_comparator,
            "else_rate_by_level": else_rate_by_level,
        }

    @staticmethod
    def back_card_usage_by_place_by_level(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Count Back card usage by place_before per level.

        Returns:
            List of dicts with level, place_before, count
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values("run__level", "chosen_card", "place_before")

        counts = defaultdict(int)
        for turn in turns:
            card = parse_card(turn.get("chosen_card"))
            if card["family"] != "back":
                continue
            level = turn.get("run__level")
            place_before = turn.get("place_before")
            if place_before is None:
                continue
            counts[(level, place_before)] += 1

        return [
            {
                "level": level,
                "place_before": place,
                "count": count,
            }
            for (level, place), count in sorted(counts.items())
        ]

    @staticmethod
    def foreach_tile_context_usage_by_level(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        ForXMoveY usage when opponents are on the target tile type per level.

        Returns:
            List of dicts with level, with_opponent, without_opponent, total
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values(
            "run_id",
            "run__level",
            "chosen_card",
            "bot_positions_before",
            "run__game_map",
        )

        map_cache = {}
        with_opponent = defaultdict(int)
        without_opponent = defaultdict(int)

        for turn in turns:
            card = parse_card(turn.get("chosen_card"))
            if card["family"] != "foreach_tile":
                continue
            target_tile_type = card["tile_type"]
            if target_tile_type is None:
                continue

            level = turn.get("run__level")
            run_id = turn.get("run_id")
            if run_id not in map_cache:
                game_map = turn.get("run__game_map") or []
                map_cache[run_id] = {
                    tile.get("tileMapIndex"): tile.get(
                        "tileType", tile.get("tileIndex")
                    )
                    for tile in game_map
                    if isinstance(tile, dict) and tile.get("tileMapIndex") is not None
                }

            map_lookup = map_cache.get(run_id, {})
            bot_positions = turn.get("bot_positions_before") or []

            opponent_on_tile = False
            for bot in bot_positions:
                if not isinstance(bot, dict):
                    continue
                bot_index = bot.get("tileMapIndex")
                if map_lookup.get(bot_index) == target_tile_type:
                    opponent_on_tile = True
                    break

            if opponent_on_tile:
                with_opponent[level] += 1
            else:
                without_opponent[level] += 1

        results = []
        for level in sorted(
            set(list(with_opponent.keys()) + list(without_opponent.keys()))
        ):
            total = with_opponent.get(level, 0) + without_opponent.get(level, 0)
            results.append(
                {
                    "level": level,
                    "with_opponent": with_opponent.get(level, 0),
                    "without_opponent": without_opponent.get(level, 0),
                    "total": total,
                }
            )

        return results

    @staticmethod
    def special_tile_chain_length_distribution_by_level(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Distribution of special tile trigger chain lengths per turn by level.

        Returns:
            List of dicts with level, chain_length, turn_count
        """
        turn_queryset = TurnEvent.objects.all()
        trigger_queryset = SpecialTileTrigger.objects.all()

        if student_ids:
            turn_queryset = turn_queryset.filter(run__student_id__in=student_ids)
            trigger_queryset = trigger_queryset.filter(
                turn__run__student_id__in=student_ids
            )
        elif classroom_id:
            turn_queryset = turn_queryset.filter(
                run__student__classroom_id=classroom_id
            )
            trigger_queryset = trigger_queryset.filter(
                turn__run__student__classroom_id=classroom_id
            )
        elif teacher:
            turn_queryset = turn_queryset.filter(
                run__student__classroom__teacher=teacher
            )
            trigger_queryset = trigger_queryset.filter(
                turn__run__student__classroom__teacher=teacher
            )

        turns_by_level = turn_queryset.values("run__level").annotate(total=Count("id"))
        total_turns_by_level = {
            entry["run__level"]: entry["total"] for entry in turns_by_level
        }

        trigger_counts = trigger_queryset.values(
            "turn_id", "turn__run__level"
        ).annotate(chain_length=Count("id"))

        distribution = defaultdict(lambda: defaultdict(int))
        turns_with_triggers = defaultdict(int)

        for entry in trigger_counts:
            level = entry["turn__run__level"]
            chain_length = entry["chain_length"]
            distribution[level][chain_length] += 1
            turns_with_triggers[level] += 1

        results = []
        for level, total_turns in total_turns_by_level.items():
            zero_count = total_turns - turns_with_triggers.get(level, 0)
            if zero_count > 0:
                distribution[level][0] += zero_count

            for chain_length, count in sorted(distribution[level].items()):
                results.append(
                    {
                        "level": level,
                        "chain_length": chain_length,
                        "turn_count": count,
                    }
                )

        return results

    @staticmethod
    def number_choice_distribution_by_level(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Distribution of chosen numbers by level.

        Returns:
            List of dicts with level, chosen_number, count
        """
        queryset = TurnEvent.objects.filter(chosen_number__isnull=False)

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        return list(
            queryset.values("run__level", "chosen_number")
            .annotate(count=Count("id"))
            .order_by("run__level", "chosen_number")
        )

    @staticmethod
    def number_decision_time_by_choice_by_level(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Average number decision time by chosen number per level.

        Returns:
            List of dicts with level, chosen_number, avg_time_ms, count
        """
        queryset = TurnEvent.objects.filter(chosen_number__isnull=False)

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        return list(
            queryset.values("run__level", "chosen_number")
            .annotate(avg_time_ms=Avg("number_decision_time_ms"), count=Count("id"))
            .order_by("run__level", "chosen_number")
        )

    @staticmethod
    def card_accuracy_by_family(teacher=None, classroom_id=None, student_ids=None):
        """
        Get accuracy rates grouped by card family.

        Returns:
            List of dicts with family, total, correct, wrong, accuracy
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values("chosen_card", "was_correct")

        counts = defaultdict(lambda: {"total": 0, "correct": 0})
        for turn in turns:
            card = parse_card(turn.get("chosen_card"))
            family = card["family"]
            counts[family]["total"] += 1
            if turn.get("was_correct"):
                counts[family]["correct"] += 1

        results = []
        for family, values in counts.items():
            total = values["total"]
            correct = values["correct"]
            results.append(
                {
                    "family": family,
                    "total": total,
                    "correct": correct,
                    "wrong": total - correct,
                    "accuracy": (correct / total * 100) if total > 0 else 0,
                }
            )

        family_order = [
            "move",
            "back",
            "conditional_tile",
            "conditional_bag_eq",
            "conditional_bag_lt",
            "conditional_bag_gt",
            "bagcount",
            "foreach_tile",
            "unknown",
        ]
        results.sort(
            key=lambda x: family_order.index(x["family"])
            if x["family"] in family_order
            else 999
        )
        return results

    @staticmethod
    def card_exposure_vs_adoption_by_family(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Compare how often card families are offered vs chosen.

        Returns:
            List of dicts with family, offered, chosen, adoption_rate
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values("chosen_card", "offered_cards")

        offered_counts = defaultdict(int)
        chosen_counts = defaultdict(int)

        for turn in turns:
            chosen_card = parse_card(turn.get("chosen_card"))
            chosen_counts[chosen_card["family"]] += 1

            offered_cards = turn.get("offered_cards") or []
            for card in offered_cards:
                offered_card = parse_card(card)
                offered_counts[offered_card["family"]] += 1

        families = set(offered_counts.keys()) | set(chosen_counts.keys())
        results = []
        for family in families:
            offered = offered_counts.get(family, 0)
            chosen = chosen_counts.get(family, 0)
            results.append(
                {
                    "family": family,
                    "offered": offered,
                    "chosen": chosen,
                    "adoption_rate": (chosen / offered * 100) if offered > 0 else 0,
                }
            )

        family_order = [
            "move",
            "back",
            "conditional_tile",
            "conditional_bag_eq",
            "conditional_bag_lt",
            "conditional_bag_gt",
            "bagcount",
            "foreach_tile",
            "unknown",
        ]
        results.sort(
            key=lambda x: family_order.index(x["family"])
            if x["family"] in family_order
            else 999
        )
        return results

    @staticmethod
    def decision_time_by_card_family(teacher=None, classroom_id=None, student_ids=None):
        """
        Get decision time statistics grouped by card family.

        Returns:
            Dict mapping family -> stats
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values("chosen_card", "card_decision_time_ms")

        family_times = defaultdict(list)
        for turn in turns:
            card = parse_card(turn.get("chosen_card"))
            decision_time = turn.get("card_decision_time_ms")
            if decision_time is not None:
                family_times[card["family"]].append(decision_time)

        result = {}
        for family, times in family_times.items():
            stats = _summary_stats(times)
            if stats:
                result[family] = stats

        return result

    @staticmethod
    def tile_conditional_accuracy_by_tile_type(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Accuracy for tile-conditional cards by tileType.

        Returns:
            Dict with by_tile_type list and overall else_rate
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values("chosen_card", "was_correct", "tile_before_type")

        counts = defaultdict(lambda: {"total": 0, "correct": 0, "else_count": 0})
        total_else = 0
        total_conditional = 0

        for turn in turns:
            card = parse_card(turn.get("chosen_card"))
            if card["family"] != "conditional_tile":
                continue
            tile_type = card["tile_type"]
            if tile_type is None:
                continue

            total_conditional += 1
            counts[tile_type]["total"] += 1
            if turn.get("was_correct"):
                counts[tile_type]["correct"] += 1

            if turn.get("tile_before_type") != tile_type:
                counts[tile_type]["else_count"] += 1
                total_else += 1

        results = []
        for tile_type, values in counts.items():
            total = values["total"]
            correct = values["correct"]
            else_count = values["else_count"]
            results.append(
                {
                    "tile_type": tile_type,
                    "total": total,
                    "correct": correct,
                    "accuracy": (correct / total * 100) if total > 0 else 0,
                    "else_rate": (else_count / total * 100) if total > 0 else 0,
                }
            )

        results.sort(key=lambda x: x["tile_type"])

        return {
            "by_tile_type": results,
            "overall_else_rate": (total_else / total_conditional * 100)
            if total_conditional > 0
            else 0,
        }

    @staticmethod
    def bag_conditional_accuracy_by_comparator(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Accuracy for bag-conditional cards by comparator (eq/lt/gt).

        Returns:
            Dict with by_comparator list and overall else_rate
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values(
            "run_id",
            "turn_index",
            "chosen_card",
            "was_correct",
            "chosen_number",
        ).order_by("run_id", "turn_index")

        counts = defaultdict(lambda: {"total": 0, "correct": 0, "else_count": 0})
        total_else = 0
        total_conditional = 0

        for turn, bag_number in _iter_turns_with_bag_number(turns):
            card = parse_card(turn.get("chosen_card"))
            comparator = BAG_COMPARATOR_BY_TYPE.get(card["type"])
            if not comparator:
                continue

            threshold = card["if_value"]
            if threshold is None or bag_number is None:
                continue

            total_conditional += 1
            counts[comparator]["total"] += 1
            if turn.get("was_correct"):
                counts[comparator]["correct"] += 1

            if comparator == "eq":
                condition_met = bag_number == threshold
            elif comparator == "lt":
                condition_met = bag_number < threshold
            else:
                condition_met = bag_number > threshold

            if not condition_met:
                counts[comparator]["else_count"] += 1
                total_else += 1

        results = []
        order = ["eq", "lt", "gt"]
        for comparator in order:
            values = counts.get(comparator)
            if not values:
                continue
            total = values["total"]
            correct = values["correct"]
            else_count = values["else_count"]
            results.append(
                {
                    "comparator": comparator,
                    "total": total,
                    "correct": correct,
                    "accuracy": (correct / total * 100) if total > 0 else 0,
                    "else_rate": (else_count / total * 100) if total > 0 else 0,
                }
            )

        return {
            "by_comparator": results,
            "overall_else_rate": (total_else / total_conditional * 100)
            if total_conditional > 0
            else 0,
        }

    @staticmethod
    def conditional_else_branch_rates(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Get overall else-branch rates for tile and bag conditionals.

        Returns:
            Dict with tile and bag else rates.
        """
        tile_data = RunAnalytics.tile_conditional_accuracy_by_tile_type(
            teacher=teacher, classroom_id=classroom_id, student_ids=student_ids
        )
        bag_data = RunAnalytics.bag_conditional_accuracy_by_comparator(
            teacher=teacher, classroom_id=classroom_id, student_ids=student_ids
        )

        return {
            "tile_else_rate": tile_data.get("overall_else_rate", 0),
            "bag_else_rate": bag_data.get("overall_else_rate", 0),
        }

    @staticmethod
    def back_card_usage_by_place(teacher=None, classroom_id=None, student_ids=None):
        """
        Count Back card usage by place_before.

        Returns:
            List of dicts with place_before and count
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values("chosen_card", "place_before")

        counts = defaultdict(int)
        for turn in turns:
            card = parse_card(turn.get("chosen_card"))
            if card["family"] != "back":
                continue
            place_before = turn.get("place_before")
            if place_before is None:
                continue
            counts[place_before] += 1

        results = [
            {"place_before": place, "count": count}
            for place, count in sorted(counts.items())
        ]
        return results

    @staticmethod
    def foreach_tile_context_usage(teacher=None, classroom_id=None, student_ids=None):
        """
        ForXMoveY usage when opponents are on the target tile type.

        Returns:
            Dict with with_opponent, without_opponent, total
        """
        queryset = TurnEvent.objects.all()

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        turns = queryset.values(
            "run_id",
            "chosen_card",
            "bot_positions_before",
            "run__game_map",
        )

        map_cache = {}
        with_opponent = 0
        without_opponent = 0

        for turn in turns:
            card = parse_card(turn.get("chosen_card"))
            if card["family"] != "foreach_tile":
                continue
            target_tile_type = card["tile_type"]
            if target_tile_type is None:
                continue

            run_id = turn.get("run_id")
            if run_id not in map_cache:
                game_map = turn.get("run__game_map") or []
                map_cache[run_id] = {
                    tile.get("tileMapIndex"): tile.get(
                        "tileType", tile.get("tileIndex")
                    )
                    for tile in game_map
                    if isinstance(tile, dict) and tile.get("tileMapIndex") is not None
                }

            map_lookup = map_cache.get(run_id, {})
            bot_positions = turn.get("bot_positions_before") or []

            opponent_on_tile = False
            for bot in bot_positions:
                if not isinstance(bot, dict):
                    continue
                bot_index = bot.get("tileMapIndex")
                if map_lookup.get(bot_index) == target_tile_type:
                    opponent_on_tile = True
                    break

            if opponent_on_tile:
                with_opponent += 1
            else:
                without_opponent += 1

        total = with_opponent + without_opponent
        return {
            "with_opponent": with_opponent,
            "without_opponent": without_opponent,
            "total": total,
        }

    @staticmethod
    def special_tile_chain_length_distribution(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Distribution of special tile trigger chain lengths per turn.

        Returns:
            List of dicts with chain_length and turn_count
        """
        turn_queryset = TurnEvent.objects.all()
        trigger_queryset = SpecialTileTrigger.objects.all()

        if student_ids:
            turn_queryset = turn_queryset.filter(run__student_id__in=student_ids)
            trigger_queryset = trigger_queryset.filter(
                turn__run__student_id__in=student_ids
            )
        elif classroom_id:
            turn_queryset = turn_queryset.filter(
                run__student__classroom_id=classroom_id
            )
            trigger_queryset = trigger_queryset.filter(
                turn__run__student__classroom_id=classroom_id
            )
        elif teacher:
            turn_queryset = turn_queryset.filter(
                run__student__classroom__teacher=teacher
            )
            trigger_queryset = trigger_queryset.filter(
                turn__run__student__classroom__teacher=teacher
            )

        total_turns = turn_queryset.count()
        trigger_counts = trigger_queryset.values("turn_id").annotate(
            chain_length=Count("id")
        )

        distribution = defaultdict(int)
        turns_with_triggers = 0
        for entry in trigger_counts:
            chain_length = entry["chain_length"]
            distribution[chain_length] += 1
            turns_with_triggers += 1

        zero_count = total_turns - turns_with_triggers
        if zero_count > 0:
            distribution[0] += zero_count

        return [
            {"chain_length": length, "turn_count": count}
            for length, count in sorted(distribution.items())
        ]

    @staticmethod
    def number_choice_distribution(teacher=None, classroom_id=None, student_ids=None):
        """
        Distribution of chosen numbers for number selection.

        Returns:
            List of dicts with chosen_number and count
        """
        queryset = TurnEvent.objects.filter(chosen_number__isnull=False)

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        data = (
            queryset.values("chosen_number")
            .annotate(count=Count("id"))
            .order_by("chosen_number")
        )
        return list(data)

    @staticmethod
    def number_decision_time_by_choice(
        teacher=None, classroom_id=None, student_ids=None
    ):
        """
        Average decision time by chosen number.

        Returns:
            List of dicts with chosen_number and avg_time_ms
        """
        queryset = TurnEvent.objects.filter(chosen_number__isnull=False)

        if student_ids:
            queryset = queryset.filter(run__student_id__in=student_ids)
        elif classroom_id:
            queryset = queryset.filter(run__student__classroom_id=classroom_id)
        elif teacher:
            queryset = queryset.filter(run__student__classroom__teacher=teacher)

        data = (
            queryset.values("chosen_number")
            .annotate(
                avg_time_ms=Avg("number_decision_time_ms"),
                count=Count("id"),
            )
            .order_by("chosen_number")
        )

        return list(data)

    @staticmethod
    def student_learning_curve_from_runs(student_id, level=None):
        """
        Get learning curve data for a student using Run model.

        Args:
            student_id: The student ID to get learning curve for
            level: Optional level filter

        Returns:
            List of per-attempt dicts with accuracy, score, time_seconds, created_at, level
        """
        queryset = Run.objects.filter(student_id=student_id)

        if level is not None:
            queryset = queryset.filter(level=level)

        runs = queryset.order_by("created_at").values(
            "correct_moves", "wrong_moves", "score", "elapsed_ms", "created_at", "level"
        )

        attempts = []
        for i, run in enumerate(runs):
            total = (run["correct_moves"] or 0) + (run["wrong_moves"] or 0)
            accuracy = ((run["correct_moves"] or 0) / total * 100) if total > 0 else 0
            attempts.append(
                {
                    "attempt": i + 1,
                    "accuracy": accuracy,
                    "score": run["score"],
                    "time_seconds": (run["elapsed_ms"] or 0) / 1000,
                    "created_at": run["created_at"],
                    "level": run["level"],
                }
            )

        return attempts
