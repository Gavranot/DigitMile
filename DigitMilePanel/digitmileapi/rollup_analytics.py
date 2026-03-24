from collections import defaultdict

from django.db.models import Count, Max, Min, Q, Sum

from .analytics import BAG_COMPARATOR_BY_TYPE, parse_card
from .models import (
    Run,
    SpecialTileTrigger,
    TurnEvent,
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
)
from .weekly_rollups import (
    clip_decision_time_ms,
    sample_stddev_from_stats,
    week_start_for,
)


def _apply_student_scope(queryset, student_ids, field_name):
    if student_ids is not None:
        if len(student_ids) == 0:
            return queryset.none()
        return queryset.filter(**{f"{field_name}__in": student_ids})
    return queryset


def _raw_runs(student_ids=None):
    queryset = Run.objects.filter(raw_data_compacted_at__isnull=True)
    return _apply_student_scope(queryset, student_ids, "student_id")


def _raw_turns(student_ids=None):
    queryset = TurnEvent.objects.filter(run__raw_data_compacted_at__isnull=True)
    return _apply_student_scope(queryset, student_ids, "run__student_id")


def _raw_triggers(student_ids=None):
    queryset = SpecialTileTrigger.objects.filter(
        turn__run__raw_data_compacted_at__isnull=True
    )
    return _apply_student_scope(queryset, student_ids, "turn__run__student_id")


def _rollup_scope(queryset, student_ids):
    return _apply_student_scope(queryset, student_ids, "student_id")


def _merge_stat_bucket(target, stats):
    target["sum"] += stats.get("sum", 0) or 0
    target["count"] += stats.get("count", 0) or 0
    target["sum_sq"] += stats.get("sum_sq", 0) or 0
    target["clipped_sum"] += stats.get("clipped_sum", 0) or 0
    target["clipped_sum_sq"] += stats.get("clipped_sum_sq", 0) or 0
    target["outlier_count"] += stats.get("outlier_count", 0) or 0

    min_value = stats.get("min")
    max_value = stats.get("max")
    if min_value is not None:
        target["min"] = (
            min_value if target["min"] is None else min(target["min"], min_value)
        )
    if max_value is not None:
        target["max"] = (
            max_value if target["max"] is None else max(target["max"], max_value)
        )


def _decision_time_bucket():
    return {
        "sum": 0,
        "count": 0,
        "sum_sq": 0,
        "min": None,
        "max": None,
        "clipped_sum": 0,
        "clipped_sum_sq": 0,
        "outlier_count": 0,
    }


def _serialize_decision_time_bucket(values):
    count = values["count"]
    clipped_avg = (values["clipped_sum"] / count) if count > 0 else 0
    raw_avg = (values["sum"] / count) if count > 0 else 0
    return {
        "count": count,
        "avg": clipped_avg,
        "clipped_avg": clipped_avg,
        "raw_avg": raw_avg,
        "min": values["min"],
        "max": values["max"],
        "stddev": sample_stddev_from_stats(values["sum"], values["sum_sq"], count),
        "clipped_stddev": sample_stddev_from_stats(
            values["clipped_sum"],
            values["clipped_sum_sq"],
            count,
        ),
        "outlier_count": values["outlier_count"],
    }


def win_rate_by_level(student_ids=None):
    combined = defaultdict(lambda: {"total_runs": 0, "wins": 0})

    for row in (
        _rollup_scope(StudentWeekLevelStats.objects.all(), student_ids)
        .values("level")
        .annotate(total_runs=Sum("runs"), wins=Sum("wins"))
    ):
        combined[row["level"]]["total_runs"] += row["total_runs"] or 0
        combined[row["level"]]["wins"] += row["wins"] or 0

    for row in (
        _raw_runs(student_ids)
        .values("level")
        .annotate(total_runs=Count("id"), wins=Count("id", filter=Q(player_won=True)))
    ):
        combined[row["level"]]["total_runs"] += row["total_runs"] or 0
        combined[row["level"]]["wins"] += row["wins"] or 0

    return [
        {
            "level": level,
            "total_runs": values["total_runs"],
            "wins": values["wins"],
            "win_rate": (values["wins"] / values["total_runs"] * 100)
            if values["total_runs"] > 0
            else 0,
        }
        for level, values in sorted(combined.items())
    ]


def wrong_moves_rate_by_level(student_ids=None):
    combined = defaultdict(lambda: {"total_correct": 0, "total_wrong": 0})

    for row in (
        _rollup_scope(StudentWeekLevelStats.objects.all(), student_ids)
        .values("level")
        .annotate(total_correct=Sum("correct_moves"), total_wrong=Sum("wrong_moves"))
    ):
        combined[row["level"]]["total_correct"] += row["total_correct"] or 0
        combined[row["level"]]["total_wrong"] += row["total_wrong"] or 0

    for row in (
        _raw_runs(student_ids)
        .values("level")
        .annotate(total_correct=Sum("correct_moves"), total_wrong=Sum("wrong_moves"))
    ):
        combined[row["level"]]["total_correct"] += row["total_correct"] or 0
        combined[row["level"]]["total_wrong"] += row["total_wrong"] or 0

    results = []
    for level, values in sorted(combined.items()):
        total_moves = values["total_correct"] + values["total_wrong"]
        results.append(
            {
                "level": level,
                "total_correct": values["total_correct"],
                "total_wrong": values["total_wrong"],
                "total_moves": total_moves,
                "wrong_rate": (values["total_wrong"] / total_moves * 100)
                if total_moves > 0
                else 0,
            }
        )
    return results


def time_distribution_by_level(student_ids=None):
    combined = defaultdict(
        lambda: {
            "elapsed_sum": 0,
            "elapsed_count": 0,
            "elapsed_sum_sq": 0,
            "min_time_ms": None,
            "max_time_ms": None,
        }
    )

    for row in (
        _rollup_scope(StudentWeekLevelStats.objects.all(), student_ids)
        .values("level")
        .annotate(
            elapsed_sum=Sum("elapsed_sum_ms"),
            elapsed_count=Sum("elapsed_count"),
            elapsed_sum_sq=Sum("elapsed_sum_sq"),
            min_time_ms=Min("elapsed_min_ms"),
            max_time_ms=Max("elapsed_max_ms"),
        )
    ):
        level = row["level"]
        combined[level]["elapsed_sum"] += row["elapsed_sum"] or 0
        combined[level]["elapsed_count"] += row["elapsed_count"] or 0
        combined[level]["elapsed_sum_sq"] += row["elapsed_sum_sq"] or 0
        if row["min_time_ms"] is not None:
            current_min = combined[level]["min_time_ms"]
            combined[level]["min_time_ms"] = (
                row["min_time_ms"]
                if current_min is None
                else min(current_min, row["min_time_ms"])
            )
        if row["max_time_ms"] is not None:
            current_max = combined[level]["max_time_ms"]
            combined[level]["max_time_ms"] = (
                row["max_time_ms"]
                if current_max is None
                else max(current_max, row["max_time_ms"])
            )

    for row in _raw_runs(student_ids).values("level", "elapsed_ms"):
        level = row["level"]
        elapsed_ms = row["elapsed_ms"] or 0
        combined[level]["elapsed_sum"] += elapsed_ms
        combined[level]["elapsed_count"] += 1
        combined[level]["elapsed_sum_sq"] += elapsed_ms * elapsed_ms
        current_min = combined[level]["min_time_ms"]
        current_max = combined[level]["max_time_ms"]
        combined[level]["min_time_ms"] = (
            elapsed_ms if current_min is None else min(current_min, elapsed_ms)
        )
        combined[level]["max_time_ms"] = (
            elapsed_ms if current_max is None else max(current_max, elapsed_ms)
        )

    results = []
    for level, values in sorted(combined.items()):
        count = values["elapsed_count"]
        results.append(
            {
                "level": level,
                "avg_time_ms": (values["elapsed_sum"] / count) if count > 0 else 0,
                "min_time_ms": values["min_time_ms"],
                "max_time_ms": values["max_time_ms"],
                "std_time_ms": sample_stddev_from_stats(
                    values["elapsed_sum"], values["elapsed_sum_sq"], count
                ),
                "run_count": count,
            }
        )
    return results


def mistake_hotspots_by_level(student_ids=None):
    results = defaultdict(lambda: defaultdict(int))

    for row in (
        _rollup_scope(StudentWeekHotspotStats.objects.all(), student_ids)
        .values("level", "tile_before_index")
        .annotate(mistake_count=Sum("mistake_count"))
    ):
        results[row["level"]][row["tile_before_index"]] += row["mistake_count"] or 0

    for row in (
        _raw_turns(student_ids)
        .filter(was_correct=False)
        .values("run__level", "tile_before_index")
        .annotate(mistake_count=Count("id"))
    ):
        results[row["run__level"]][row["tile_before_index"]] += (
            row["mistake_count"] or 0
        )

    return {level: dict(values) for level, values in results.items()}


def special_tile_breakdown(student_ids=None):
    combined = defaultdict(int)

    for row in (
        _rollup_scope(StudentWeekSpecialTileStats.objects.all(), student_ids)
        .values("level", "special_tile_type")
        .annotate(trigger_count=Sum("trigger_count"))
    ):
        combined[(row["level"], row["special_tile_type"])] += row["trigger_count"] or 0

    for row in (
        _raw_triggers(student_ids)
        .values("turn__run__level", "special_tile_type")
        .annotate(trigger_count=Count("id"))
    ):
        combined[(row["turn__run__level"], row["special_tile_type"])] += (
            row["trigger_count"] or 0
        )

    return [
        {
            "turn__run__level": level,
            "special_tile_type": special_tile_type,
            "trigger_count": count,
        }
        for (level, special_tile_type), count in sorted(combined.items())
    ]


def offer_choice_share_by_family(student_ids=None):
    combined = defaultdict(lambda: {"offered": 0, "chosen": 0})
    offered_totals = defaultdict(int)
    chosen_totals = defaultdict(int)

    for row in (
        _rollup_scope(StudentWeekCardFamilyStats.objects.all(), student_ids)
        .values("level", "card_family")
        .annotate(offered=Sum("offered_count"), chosen=Sum("chosen_count"))
    ):
        key = (row["level"], row["card_family"])
        offered = row["offered"] or 0
        chosen = row["chosen"] or 0
        combined[key]["offered"] += offered
        combined[key]["chosen"] += chosen
        offered_totals[row["level"]] += offered
        chosen_totals[row["level"]] += chosen

    for turn in _raw_turns(student_ids).values(
        "run__level", "chosen_card_family", "chosen_card", "offered_cards"
    ):
        level = turn["run__level"]
        chosen_family = turn["chosen_card_family"] or parse_card(
            turn["chosen_card"]
        ).get("family", "unknown")
        combined[(level, chosen_family)]["chosen"] += 1
        chosen_totals[level] += 1

        for card in turn.get("offered_cards") or []:
            offered_family = parse_card(card).get("family", "unknown")
            combined[(level, offered_family)]["offered"] += 1
            offered_totals[level] += 1

    results = []
    for (level, family), values in sorted(combined.items()):
        offered = values["offered"]
        chosen = values["chosen"]
        total_offered = offered_totals[level]
        total_chosen = chosen_totals[level]
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


def card_accuracy_by_family_by_level(student_ids=None):
    combined = defaultdict(lambda: {"total": 0, "correct": 0})

    for row in (
        _rollup_scope(StudentWeekCardFamilyStats.objects.all(), student_ids)
        .values("level", "card_family")
        .annotate(
            correct=Sum("correct_count"),
            wrong=Sum("wrong_count"),
        )
    ):
        total = (row["correct"] or 0) + (row["wrong"] or 0)
        key = (row["level"], row["card_family"])
        combined[key]["total"] += total
        combined[key]["correct"] += row["correct"] or 0

    for turn in _raw_turns(student_ids).values(
        "run__level", "chosen_card_family", "chosen_card", "was_correct"
    ):
        family = turn["chosen_card_family"] or parse_card(turn["chosen_card"]).get(
            "family", "unknown"
        )
        key = (turn["run__level"], family)
        combined[key]["total"] += 1
        if turn["was_correct"]:
            combined[key]["correct"] += 1

    results = []
    for (level, family), values in sorted(combined.items()):
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


def decision_time_by_family_by_level(student_ids=None):
    combined = defaultdict(
        lambda: {"sum": 0, "count": 0, "sum_sq": 0, "min": None, "max": None}
    )

    for row in (
        _rollup_scope(StudentWeekCardFamilyStats.objects.all(), student_ids)
        .values("level", "card_family")
        .annotate(
            total_sum=Sum("decision_time_sum_ms"),
            total_count=Sum("decision_time_count"),
            total_sum_sq=Sum("decision_time_sum_sq_ms"),
            min_time=Min("decision_time_min_ms"),
            max_time=Max("decision_time_max_ms"),
        )
    ):
        key = (row["level"], row["card_family"])
        combined[key]["sum"] += row["total_sum"] or 0
        combined[key]["count"] += row["total_count"] or 0
        combined[key]["sum_sq"] += row["total_sum_sq"] or 0
        if row["min_time"] is not None:
            current_min = combined[key]["min"]
            combined[key]["min"] = (
                row["min_time"]
                if current_min is None
                else min(current_min, row["min_time"])
            )
        if row["max_time"] is not None:
            current_max = combined[key]["max"]
            combined[key]["max"] = (
                row["max_time"]
                if current_max is None
                else max(current_max, row["max_time"])
            )

    for turn in _raw_turns(student_ids).values(
        "run__level", "chosen_card_family", "chosen_card", "card_decision_time_ms"
    ):
        family = turn["chosen_card_family"] or parse_card(turn["chosen_card"]).get(
            "family", "unknown"
        )
        key = (turn["run__level"], family)
        decision_time = turn["card_decision_time_ms"] or 0
        combined[key]["sum"] += decision_time
        combined[key]["count"] += 1
        combined[key]["sum_sq"] += decision_time * decision_time
        combined[key]["min"] = (
            decision_time
            if combined[key]["min"] is None
            else min(combined[key]["min"], decision_time)
        )
        combined[key]["max"] = (
            decision_time
            if combined[key]["max"] is None
            else max(combined[key]["max"], decision_time)
        )

    results = []
    for (level, family), values in sorted(combined.items()):
        count = values["count"]
        avg = (values["sum"] / count) if count > 0 else 0
        results.append(
            {
                "level": level,
                "family": family,
                "count": count,
                "avg": avg,
                "min": values["min"],
                "max": values["max"],
                "median": avg,
                "q1": values["min"],
                "q3": values["max"],
                "stddev": sample_stddev_from_stats(
                    values["sum"], values["sum_sq"], count
                ),
            }
        )
    return results


def decision_time_by_card_type(student_ids=None):
    summary = defaultdict(_decision_time_bucket)
    weekly = defaultdict(lambda: defaultdict(_decision_time_bucket))

    for row in (
        _rollup_scope(StudentWeekCardTypeStats.objects.all(), student_ids)
        .values("week_start", "card_type")
        .annotate(
            chosen_count=Sum("chosen_count"),
            total_sum=Sum("decision_time_sum_ms"),
            total_count=Sum("decision_time_count"),
            total_sum_sq=Sum("decision_time_sum_sq_ms"),
            min_time=Min("decision_time_min_ms"),
            max_time=Max("decision_time_max_ms"),
            clipped_sum=Sum("clipped_decision_time_sum_ms"),
            clipped_sum_sq=Sum("clipped_decision_time_sum_sq_ms"),
            outlier_count=Sum("outlier_count"),
        )
    ):
        card_type = row["card_type"]
        week_bucket = weekly[card_type][str(row["week_start"])]
        bucket_values = {
            "sum": row["total_sum"] or 0,
            "count": row["total_count"] or 0,
            "sum_sq": row["total_sum_sq"] or 0,
            "min": row["min_time"],
            "max": row["max_time"],
            "clipped_sum": row["clipped_sum"] or 0,
            "clipped_sum_sq": row["clipped_sum_sq"] or 0,
            "outlier_count": row["outlier_count"] or 0,
        }
        _merge_stat_bucket(summary[card_type], bucket_values)
        _merge_stat_bucket(week_bucket, bucket_values)

    for turn in _raw_turns(student_ids).values(
        "run__created_at",
        "chosen_card_type",
        "chosen_card",
        "card_decision_time_ms",
    ):
        card_type = turn["chosen_card_type"] or parse_card(turn["chosen_card"]).get(
            "type", "unknown"
        )
        if not card_type or card_type == "unknown":
            card_type = parse_card(turn["chosen_card"]).get("type", "unknown")
        decision_time = turn["card_decision_time_ms"] or 0
        clipped_value, was_clipped = clip_decision_time_ms(decision_time)
        week_start = str(week_start_for(turn["run__created_at"]))
        bucket_values = {
            "sum": decision_time,
            "count": 1,
            "sum_sq": decision_time * decision_time,
            "min": decision_time,
            "max": decision_time,
            "clipped_sum": clipped_value,
            "clipped_sum_sq": clipped_value * clipped_value,
            "outlier_count": 1 if was_clipped else 0,
        }
        _merge_stat_bucket(summary[card_type], bucket_values)
        _merge_stat_bucket(weekly[card_type][week_start], bucket_values)

    summary_by_card_type = {
        card_type: _serialize_decision_time_bucket(values)
        for card_type, values in sorted(summary.items())
    }
    weekly_series_by_card_type = {
        card_type: [
            {"week_start": week_start, **_serialize_decision_time_bucket(values)}
            for week_start, values in sorted(week_values.items())
        ]
        for card_type, week_values in sorted(weekly.items())
    }

    return {
        "summary_by_card_type": summary_by_card_type,
        "weekly_series_by_card_type": weekly_series_by_card_type,
    }


def tile_conditional_accuracy_by_tile_type_by_level(student_ids=None):
    counts = defaultdict(lambda: {"total": 0, "correct": 0, "else_count": 0})
    total_else_by_level = defaultdict(int)
    total_conditional_by_level = defaultdict(int)

    for row in (
        _rollup_scope(
            StudentWeekConditionalStats.objects.filter(
                conditional_kind=StudentWeekConditionalStats.ConditionalKind.TILE
            ),
            student_ids,
        )
        .values("level", "bucket_key")
        .annotate(
            total=Sum("total_count"),
            correct=Sum("correct_count"),
            else_count=Sum("else_count"),
        )
    ):
        level = row["level"]
        tile_type = int(row["bucket_key"])
        total = row["total"] or 0
        else_count = row["else_count"] or 0
        counts[(level, tile_type)]["total"] += total
        counts[(level, tile_type)]["correct"] += row["correct"] or 0
        counts[(level, tile_type)]["else_count"] += else_count
        total_conditional_by_level[level] += total
        total_else_by_level[level] += else_count

    for turn in (
        _raw_turns(student_ids)
        .filter(chosen_card_family="conditional_tile")
        .values(
            "run__level",
            "chosen_card_tile_type",
            "chosen_card",
            "was_correct",
            "tile_before_type",
        )
    ):
        tile_type = turn["chosen_card_tile_type"]
        if tile_type is None:
            tile_type = parse_card(turn["chosen_card"]).get("tile_type")
        if tile_type is None:
            continue

        level = turn["run__level"]
        counts[(level, tile_type)]["total"] += 1
        total_conditional_by_level[level] += 1
        if turn["was_correct"]:
            counts[(level, tile_type)]["correct"] += 1
        if turn["tile_before_type"] != tile_type:
            counts[(level, tile_type)]["else_count"] += 1
            total_else_by_level[level] += 1

    by_tile_type = []
    for (level, tile_type), values in sorted(counts.items()):
        total = values["total"]
        else_count = values["else_count"]
        by_tile_type.append(
            {
                "level": level,
                "tile_type": tile_type,
                "total": total,
                "correct": values["correct"],
                "accuracy": (values["correct"] / total * 100) if total > 0 else 0,
                "else_rate": (else_count / total * 100) if total > 0 else 0,
            }
        )

    else_rate_by_level = [
        {
            "level": level,
            "else_rate": (
                total_else_by_level[level] / total_conditional_by_level[level] * 100
            )
            if total_conditional_by_level[level] > 0
            else 0,
        }
        for level in sorted(total_conditional_by_level.keys())
    ]

    return {
        "by_tile_type": by_tile_type,
        "else_rate_by_level": else_rate_by_level,
    }


def bag_conditional_accuracy_by_comparator_by_level(student_ids=None):
    counts = defaultdict(lambda: {"total": 0, "correct": 0, "else_count": 0})
    total_else_by_level = defaultdict(int)
    total_conditional_by_level = defaultdict(int)

    for row in (
        _rollup_scope(
            StudentWeekConditionalStats.objects.filter(
                conditional_kind=StudentWeekConditionalStats.ConditionalKind.BAG
            ),
            student_ids,
        )
        .values("level", "bucket_key")
        .annotate(
            total=Sum("total_count"),
            correct=Sum("correct_count"),
            else_count=Sum("else_count"),
        )
    ):
        level = row["level"]
        comparator = row["bucket_key"]
        total = row["total"] or 0
        else_count = row["else_count"] or 0
        counts[(level, comparator)]["total"] += total
        counts[(level, comparator)]["correct"] += row["correct"] or 0
        counts[(level, comparator)]["else_count"] += else_count
        total_conditional_by_level[level] += total
        total_else_by_level[level] += else_count

    # Fetch bag-conditional turns AND any turn that updates chosen_number
    # (bag state). Without the chosen_number turns, bag_number tracking
    # across a run would use stale values and else_rate would be wrong.
    raw_turns = (
        _raw_turns(student_ids)
        .filter(
            Q(
                chosen_card_family__in=[
                    "conditional_bag_eq",
                    "conditional_bag_lt",
                    "conditional_bag_gt",
                ]
            )
            | Q(chosen_number__isnull=False)
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
    for turn in raw_turns:
        if turn["run_id"] != current_run_id:
            current_run_id = turn["run_id"]
            bag_number = 1

        card_data = parse_card(turn["chosen_card"])
        comparator = BAG_COMPARATOR_BY_TYPE.get(turn["chosen_card_type"])
        threshold = card_data.get("if_value")
        if comparator is None or threshold is None:
            if turn["chosen_number"] is not None:
                bag_number = turn["chosen_number"]
            continue

        level = turn["run__level"]
        counts[(level, comparator)]["total"] += 1
        total_conditional_by_level[level] += 1
        if turn["was_correct"]:
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

        if turn["chosen_number"] is not None:
            bag_number = turn["chosen_number"]

    by_comparator = []
    for (level, comparator), values in sorted(counts.items()):
        total = values["total"]
        else_count = values["else_count"]
        by_comparator.append(
            {
                "level": level,
                "comparator": comparator,
                "total": total,
                "correct": values["correct"],
                "accuracy": (values["correct"] / total * 100) if total > 0 else 0,
                "else_rate": (else_count / total * 100) if total > 0 else 0,
            }
        )

    else_rate_by_level = [
        {
            "level": level,
            "else_rate": (
                total_else_by_level[level] / total_conditional_by_level[level] * 100
            )
            if total_conditional_by_level[level] > 0
            else 0,
        }
        for level in sorted(total_conditional_by_level.keys())
    ]

    return {
        "by_comparator": by_comparator,
        "else_rate_by_level": else_rate_by_level,
    }


def back_card_usage_by_place_by_level(student_ids=None):
    combined = defaultdict(int)

    for row in (
        _rollup_scope(StudentWeekBackCardUsageStats.objects.all(), student_ids)
        .values("level", "place_before")
        .annotate(total=Sum("count"))
    ):
        combined[(row["level"], row["place_before"])] += row["total"] or 0

    for row in (
        _raw_turns(student_ids)
        .filter(chosen_card_family="back")
        .values("run__level", "place_before")
        .annotate(total=Count("id"))
    ):
        combined[(row["run__level"], row["place_before"])] += row["total"] or 0

    return [
        {"level": level, "place_before": place_before, "count": count}
        for (level, place_before), count in sorted(combined.items())
    ]


def foreach_tile_context_usage_by_level(student_ids=None):
    combined = defaultdict(lambda: {"with_opponent": 0, "without_opponent": 0})

    for row in (
        _rollup_scope(
            StudentWeekForeachContextStats.objects.all(),
            student_ids,
        )
        .values("level")
        .annotate(
            with_opponent=Sum("with_opponent_count"),
            without_opponent=Sum("without_opponent_count"),
        )
    ):
        combined[row["level"]]["with_opponent"] += row["with_opponent"] or 0
        combined[row["level"]]["without_opponent"] += row["without_opponent"] or 0

    for turn in (
        _raw_turns(student_ids)
        .filter(chosen_card_family="foreach_tile")
        .values(
            "run__level",
            "chosen_card_tile_type",
            "chosen_card",
            "bot_positions_before",
            "run__game_map",
        )
    ):
        tile_type = turn["chosen_card_tile_type"]
        if tile_type is None:
            tile_type = parse_card(turn["chosen_card"]).get("tile_type")
        if tile_type is None:
            continue

        map_lookup = {}
        for tile in turn.get("run__game_map") or []:
            if isinstance(tile, dict) and tile.get("tileMapIndex") is not None:
                map_lookup[tile["tileMapIndex"]] = tile.get(
                    "tileType", tile.get("tileIndex")
                )

        opponent_on_tile = False
        for bot in turn.get("bot_positions_before") or []:
            if (
                isinstance(bot, dict)
                and map_lookup.get(bot.get("tileMapIndex")) == tile_type
            ):
                opponent_on_tile = True
                break

        level = turn["run__level"]
        if opponent_on_tile:
            combined[level]["with_opponent"] += 1
        else:
            combined[level]["without_opponent"] += 1

    return [
        {
            "level": level,
            "with_opponent": values["with_opponent"],
            "without_opponent": values["without_opponent"],
            "total": values["with_opponent"] + values["without_opponent"],
        }
        for level, values in sorted(combined.items())
    ]


def special_tile_chain_length_distribution_by_level(student_ids=None):
    combined = defaultdict(int)

    for row in (
        _rollup_scope(
            StudentWeekChainLengthStats.objects.all(),
            student_ids,
        )
        .values("level", "chain_length")
        .annotate(total=Sum("turn_count"))
    ):
        combined[(row["level"], row["chain_length"])] += row["total"] or 0

    for row in (
        _raw_turns(student_ids)
        .values("run__level", "id")
        .annotate(chain_length=Count("special_tile_triggers"))
    ):
        combined[(row["run__level"], row["chain_length"])] += 1

    return [
        {"level": level, "chain_length": chain_length, "turn_count": count}
        for (level, chain_length), count in sorted(combined.items())
    ]


def number_choice_distribution_by_level(student_ids=None):
    combined = defaultdict(int)

    for row in (
        _rollup_scope(
            StudentWeekNumberChoiceStats.objects.all(),
            student_ids,
        )
        .values("level", "chosen_number")
        .annotate(total=Sum("choice_count"))
    ):
        combined[(row["level"], row["chosen_number"])] += row["total"] or 0

    for row in (
        _raw_turns(student_ids)
        .filter(chosen_number__isnull=False)
        .values("run__level", "chosen_number")
        .annotate(total=Count("id"))
    ):
        combined[(row["run__level"], row["chosen_number"])] += row["total"] or 0

    return [
        {"level": level, "chosen_number": chosen_number, "count": count}
        for (level, chosen_number), count in sorted(combined.items())
    ]


def number_decision_time_by_choice_by_level(student_ids=None):
    combined = defaultdict(
        lambda: {"sum": 0, "count": 0, "sum_sq": 0, "min": None, "max": None}
    )

    for row in (
        _rollup_scope(
            StudentWeekNumberChoiceStats.objects.all(),
            student_ids,
        )
        .values("level", "chosen_number")
        .annotate(
            total_sum=Sum("decision_time_sum_ms"),
            total_count=Sum("decision_time_count"),
            total_sum_sq=Sum("decision_time_sum_sq_ms"),
            min_time=Min("decision_time_min_ms"),
            max_time=Max("decision_time_max_ms"),
        )
    ):
        key = (row["level"], row["chosen_number"])
        combined[key]["sum"] += row["total_sum"] or 0
        combined[key]["count"] += row["total_count"] or 0
        combined[key]["sum_sq"] += row["total_sum_sq"] or 0
        if row["min_time"] is not None:
            current_min = combined[key]["min"]
            combined[key]["min"] = (
                row["min_time"]
                if current_min is None
                else min(current_min, row["min_time"])
            )
        if row["max_time"] is not None:
            current_max = combined[key]["max"]
            combined[key]["max"] = (
                row["max_time"]
                if current_max is None
                else max(current_max, row["max_time"])
            )

    for row in (
        _raw_turns(student_ids)
        .filter(chosen_number__isnull=False)
        .values("run__level", "chosen_number", "number_decision_time_ms")
    ):
        key = (row["run__level"], row["chosen_number"])
        decision_time = row["number_decision_time_ms"] or 0
        combined[key]["sum"] += decision_time
        combined[key]["count"] += 1
        combined[key]["sum_sq"] += decision_time * decision_time
        combined[key]["min"] = (
            decision_time
            if combined[key]["min"] is None
            else min(combined[key]["min"], decision_time)
        )
        combined[key]["max"] = (
            decision_time
            if combined[key]["max"] is None
            else max(combined[key]["max"], decision_time)
        )

    return [
        {
            "level": level,
            "chosen_number": chosen_number,
            "avg_time_ms": (values["sum"] / values["count"])
            if values["count"] > 0
            else 0,
            "count": values["count"],
            "min": values["min"],
            "max": values["max"],
            "stddev": sample_stddev_from_stats(
                values["sum"], values["sum_sq"], values["count"]
            ),
        }
        for (level, chosen_number), values in sorted(combined.items())
    ]
