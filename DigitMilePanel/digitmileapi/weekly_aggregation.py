from collections import defaultdict

from django.db import transaction
from django.db.models import Count
from django.db.models import Prefetch

from .analytics import BAG_COMPARATOR_BY_TYPE, parse_card
from .models import (
    ClassroomWeekStats,
    Run,
    SpecialTileTrigger,
    Student,
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
    TurnEvent,
)
from .weekly_rollups import clip_decision_time_ms, week_end_for, week_start_for


def _update_summary_stats(target, value, value_prefix):
    target[f"{value_prefix}_sum"] += value
    target[f"{value_prefix}_count"] += 1
    target[f"{value_prefix}_sum_sq"] += value * value

    min_key = f"{value_prefix}_min"
    max_key = f"{value_prefix}_max"
    target[min_key] = value if target[min_key] is None else min(target[min_key], value)
    target[max_key] = value if target[max_key] is None else max(target[max_key], value)


def _ensure_run_summary(target, run):
    target["runs"] += 1
    if run.player_won:
        target["wins"] += 1
    target["correct_moves"] += run.correct_moves or 0
    target["wrong_moves"] += run.wrong_moves or 0
    _update_summary_stats(target, run.score or 0, "score")
    _update_summary_stats(target, run.elapsed_ms or 0, "elapsed")

    if (
        target["latest_run_created_at"] is None
        or run.created_at > target["latest_run_created_at"]
    ):
        target["latest_run"] = run
        target["latest_run_created_at"] = run.created_at

    if target.get("first_run_created_at") is not None:
        target["first_run_created_at"] = min(
            target["first_run_created_at"], run.created_at
        )


def _default_student_week_summary():
    return {
        "runs": 0,
        "wins": 0,
        "correct_moves": 0,
        "wrong_moves": 0,
        "score_sum": 0,
        "score_count": 0,
        "score_sum_sq": 0,
        "score_min": None,
        "score_max": None,
        "elapsed_sum": 0,
        "elapsed_count": 0,
        "elapsed_sum_sq": 0,
        "elapsed_min": None,
        "elapsed_max": None,
        "latest_run": None,
        "latest_run_created_at": None,
        "first_run_created_at": None,
    }


def _default_student_week_level_summary():
    summary = _default_student_week_summary()
    summary.pop("first_run_created_at")
    return summary


def _card_family_for_turn(turn):
    if turn.chosen_card_family and turn.chosen_card_family != "unknown":
        return turn.chosen_card_family
    return parse_card(turn.chosen_card).get("family", "unknown")


def _card_type_for_turn(turn):
    if turn.chosen_card_type and turn.chosen_card_type != "unknown":
        return turn.chosen_card_type
    return parse_card(turn.chosen_card).get("type", "unknown")


def _card_tile_type_for_turn(turn):
    if turn.chosen_card_tile_type is not None:
        return turn.chosen_card_tile_type
    return parse_card(turn.chosen_card).get("tile_type")


def _map_lookup(game_map):
    lookup = {}
    for tile in game_map or []:
        if not isinstance(tile, dict):
            continue
        tile_index = tile.get("tileMapIndex")
        if tile_index is None:
            continue
        lookup[tile_index] = tile.get("tileType", tile.get("tileIndex"))
    return lookup


def _delete_existing_week_rollups(week_start):
    for model in [
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
        ClassroomWeekStats,
    ]:
        model.objects.filter(week_start=week_start).delete()


def _update_decision_time_stats(target, decision_time, include_clipped=False):
    target["decision_time_sum_ms"] += decision_time
    target["decision_time_count"] += 1
    target["decision_time_sum_sq_ms"] += decision_time * decision_time
    target["decision_time_min_ms"] = (
        decision_time
        if target["decision_time_min_ms"] is None
        else min(target["decision_time_min_ms"], decision_time)
    )
    target["decision_time_max_ms"] = (
        decision_time
        if target["decision_time_max_ms"] is None
        else max(target["decision_time_max_ms"], decision_time)
    )

    if include_clipped:
        clipped_value, was_clipped = clip_decision_time_ms(decision_time)
        target["clipped_decision_time_sum_ms"] += clipped_value
        target["clipped_decision_time_sum_sq_ms"] += clipped_value * clipped_value
        if was_clipped:
            target["outlier_count"] += 1


def aggregate_weekly_rollups(week_start):
    week_start = week_start_for(week_start)
    week_end = week_end_for(week_start)
    ordered_turns = Prefetch(
        "turn_events",
        queryset=TurnEvent.objects.order_by("turn_index").prefetch_related(
            Prefetch(
                "special_tile_triggers",
                queryset=SpecialTileTrigger.objects.order_by("chain_index"),
            )
        ),
    )

    runs = list(
        Run.objects.filter(
            created_at__date__gte=week_start, created_at__date__lte=week_end
        )
        .select_related("student__classroom__teacher")
        .prefetch_related(ordered_turns)
        .order_by("student_id", "created_at", "id")
    )

    classroom_ids = {run.student.classroom_id for run in runs}
    classroom_student_counts = {
        entry["classroom_id"]: entry["student_count"]
        for entry in Student.objects.filter(classroom_id__in=classroom_ids)
        .values("classroom_id")
        .annotate(student_count=Count("id"))
    }

    student_week = defaultdict(_default_student_week_summary)
    student_level = defaultdict(_default_student_week_level_summary)
    student_hotspots = defaultdict(int)
    student_special_tiles = defaultdict(int)
    student_chain_lengths = defaultdict(int)
    student_card_families = defaultdict(
        lambda: {
            "offered_count": 0,
            "chosen_count": 0,
            "correct_count": 0,
            "wrong_count": 0,
            "decision_time_sum_ms": 0,
            "decision_time_count": 0,
            "decision_time_sum_sq_ms": 0,
            "decision_time_min_ms": None,
            "decision_time_max_ms": None,
        }
    )
    student_conditionals = defaultdict(
        lambda: {"total_count": 0, "correct_count": 0, "else_count": 0}
    )
    student_card_types = defaultdict(
        lambda: {
            "chosen_count": 0,
            "decision_time_sum_ms": 0,
            "decision_time_count": 0,
            "decision_time_sum_sq_ms": 0,
            "decision_time_min_ms": None,
            "decision_time_max_ms": None,
            "clipped_decision_time_sum_ms": 0,
            "clipped_decision_time_sum_sq_ms": 0,
            "outlier_count": 0,
        }
    )
    student_back_usage = defaultdict(int)
    student_foreach_context = defaultdict(
        lambda: {"with_opponent_count": 0, "without_opponent_count": 0}
    )
    student_number_choices = defaultdict(
        lambda: {
            "choice_count": 0,
            "decision_time_sum_ms": 0,
            "decision_time_count": 0,
            "decision_time_sum_sq_ms": 0,
            "decision_time_min_ms": None,
            "decision_time_max_ms": None,
        }
    )
    classroom_week = defaultdict(
        lambda: {
            "runs": 0,
            "wins": 0,
            "correct_moves": 0,
            "wrong_moves": 0,
            "score_sum": 0,
            "score_count": 0,
            "score_sum_sq": 0,
            "elapsed_sum_ms": 0,
            "elapsed_count": 0,
            "elapsed_sum_sq": 0,
        }
    )

    for run in runs:
        student = run.student
        classroom = student.classroom
        teacher = classroom.teacher

        student_key = (student.id, classroom.id, teacher.id)
        level_key = (student.id, classroom.id, teacher.id, run.level)
        classroom_key = (classroom.id, teacher.id)

        student_summary = student_week[student_key]
        if student_summary["first_run_created_at"] is None:
            student_summary["first_run_created_at"] = run.created_at
        _ensure_run_summary(student_summary, run)

        level_summary = student_level[level_key]
        _ensure_run_summary(level_summary, run)

        classroom_summary = classroom_week[classroom_key]
        classroom_summary["runs"] += 1
        if run.player_won:
            classroom_summary["wins"] += 1
        classroom_summary["correct_moves"] += run.correct_moves or 0
        classroom_summary["wrong_moves"] += run.wrong_moves or 0
        classroom_summary["score_sum"] += run.score or 0
        classroom_summary["score_count"] += 1
        classroom_summary["score_sum_sq"] += (run.score or 0) * (run.score or 0)
        classroom_summary["elapsed_sum_ms"] += run.elapsed_ms or 0
        classroom_summary["elapsed_count"] += 1
        classroom_summary["elapsed_sum_sq"] += (run.elapsed_ms or 0) * (
            run.elapsed_ms or 0
        )

        bag_number = 1
        map_lookup = _map_lookup(run.game_map)

        for turn in run.turn_events.all():
            family = _card_family_for_turn(turn)
            card_type = _card_type_for_turn(turn)
            tile_type = _card_tile_type_for_turn(turn)
            card_data = parse_card(turn.chosen_card)

            family_key = (student.id, classroom.id, teacher.id, run.level, family)
            family_stats = student_card_families[family_key]
            family_stats["chosen_count"] += 1
            if turn.was_correct:
                family_stats["correct_count"] += 1
            else:
                family_stats["wrong_count"] += 1
                hotspot_key = (
                    student.id,
                    classroom.id,
                    teacher.id,
                    run.level,
                    turn.tile_before_index,
                )
                student_hotspots[hotspot_key] += 1

            decision_time = turn.card_decision_time_ms or 0
            _update_decision_time_stats(family_stats, decision_time)

            card_type_key = (student.id, classroom.id, teacher.id, run.level, card_type)
            card_type_stats = student_card_types[card_type_key]
            card_type_stats["chosen_count"] += 1
            _update_decision_time_stats(
                card_type_stats,
                decision_time,
                include_clipped=True,
            )

            for offered_card in turn.offered_cards or []:
                offered_family = parse_card(offered_card).get("family", "unknown")
                student_card_families[
                    (student.id, classroom.id, teacher.id, run.level, offered_family)
                ]["offered_count"] += 1

            chain_length = turn.special_tile_triggers.count()
            student_chain_lengths[
                (student.id, classroom.id, teacher.id, run.level, chain_length)
            ] += 1

            for trigger in turn.special_tile_triggers.all():
                student_special_tiles[
                    (
                        student.id,
                        classroom.id,
                        teacher.id,
                        run.level,
                        trigger.special_tile_type,
                    )
                ] += 1

            if family == "conditional_tile" and tile_type is not None:
                conditional_key = (
                    student.id,
                    classroom.id,
                    teacher.id,
                    run.level,
                    StudentWeekConditionalStats.ConditionalKind.TILE,
                    str(tile_type),
                )
                stats = student_conditionals[conditional_key]
                stats["total_count"] += 1
                if turn.was_correct:
                    stats["correct_count"] += 1
                if turn.tile_before_type != tile_type:
                    stats["else_count"] += 1

            if family in {
                "conditional_bag_eq",
                "conditional_bag_lt",
                "conditional_bag_gt",
            }:
                comparator = BAG_COMPARATOR_BY_TYPE.get(card_type)
                threshold = card_data.get("if_value")
                if comparator and threshold is not None:
                    conditional_key = (
                        student.id,
                        classroom.id,
                        teacher.id,
                        run.level,
                        StudentWeekConditionalStats.ConditionalKind.BAG,
                        comparator,
                    )
                    stats = student_conditionals[conditional_key]
                    stats["total_count"] += 1
                    if turn.was_correct:
                        stats["correct_count"] += 1

                    if comparator == "eq":
                        condition_met = bag_number == threshold
                    elif comparator == "lt":
                        condition_met = bag_number < threshold
                    else:
                        condition_met = bag_number > threshold

                    if not condition_met:
                        stats["else_count"] += 1

            if family == "back":
                student_back_usage[
                    (student.id, classroom.id, teacher.id, run.level, turn.place_before)
                ] += 1

            if family == "foreach_tile" and tile_type is not None:
                foreach_stats = student_foreach_context[
                    (student.id, classroom.id, teacher.id, run.level)
                ]
                opponent_on_target = False
                for bot in turn.bot_positions_before or []:
                    if not isinstance(bot, dict):
                        continue
                    if map_lookup.get(bot.get("tileMapIndex")) == tile_type:
                        opponent_on_target = True
                        break
                if opponent_on_target:
                    foreach_stats["with_opponent_count"] += 1
                else:
                    foreach_stats["without_opponent_count"] += 1

            if turn.chosen_number is not None:
                choice_key = (
                    student.id,
                    classroom.id,
                    teacher.id,
                    run.level,
                    turn.chosen_number,
                )
                choice_stats = student_number_choices[choice_key]
                choice_stats["choice_count"] += 1
                number_decision_time = turn.number_decision_time_ms or 0
                choice_stats["decision_time_sum_ms"] += number_decision_time
                choice_stats["decision_time_count"] += 1
                choice_stats["decision_time_sum_sq_ms"] += (
                    number_decision_time * number_decision_time
                )
                choice_stats["decision_time_min_ms"] = (
                    number_decision_time
                    if choice_stats["decision_time_min_ms"] is None
                    else min(choice_stats["decision_time_min_ms"], number_decision_time)
                )
                choice_stats["decision_time_max_ms"] = (
                    number_decision_time
                    if choice_stats["decision_time_max_ms"] is None
                    else max(choice_stats["decision_time_max_ms"], number_decision_time)
                )
                bag_number = turn.chosen_number

    with transaction.atomic():
        _delete_existing_week_rollups(week_start)

        StudentWeekStats.objects.bulk_create(
            [
                StudentWeekStats(
                    student_id=student_id,
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    runs=values["runs"],
                    wins=values["wins"],
                    correct_moves=values["correct_moves"],
                    wrong_moves=values["wrong_moves"],
                    score_sum=values["score_sum"],
                    score_count=values["score_count"],
                    score_sum_sq=values["score_sum_sq"],
                    score_min=values["score_min"],
                    score_max=values["score_max"],
                    elapsed_sum_ms=values["elapsed_sum"],
                    elapsed_count=values["elapsed_count"],
                    elapsed_sum_sq=values["elapsed_sum_sq"],
                    elapsed_min_ms=values["elapsed_min"],
                    elapsed_max_ms=values["elapsed_max"],
                    latest_run=values["latest_run"],
                    latest_run_created_at=values["latest_run_created_at"],
                    first_run_created_at=values["first_run_created_at"],
                )
                for (
                    student_id,
                    classroom_id,
                    teacher_id,
                ), values in student_week.items()
            ]
        )

        StudentWeekLevelStats.objects.bulk_create(
            [
                StudentWeekLevelStats(
                    student_id=student_id,
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    level=level,
                    runs=values["runs"],
                    wins=values["wins"],
                    correct_moves=values["correct_moves"],
                    wrong_moves=values["wrong_moves"],
                    score_sum=values["score_sum"],
                    score_count=values["score_count"],
                    score_sum_sq=values["score_sum_sq"],
                    score_min=values["score_min"],
                    score_max=values["score_max"],
                    elapsed_sum_ms=values["elapsed_sum"],
                    elapsed_count=values["elapsed_count"],
                    elapsed_sum_sq=values["elapsed_sum_sq"],
                    elapsed_min_ms=values["elapsed_min"],
                    elapsed_max_ms=values["elapsed_max"],
                    latest_run=values["latest_run"],
                    latest_run_created_at=values["latest_run_created_at"],
                )
                for (
                    student_id,
                    classroom_id,
                    teacher_id,
                    level,
                ), values in student_level.items()
            ]
        )

        StudentWeekHotspotStats.objects.bulk_create(
            [
                StudentWeekHotspotStats(
                    student_id=student_id,
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    level=level,
                    tile_before_index=tile_before_index,
                    mistake_count=mistake_count,
                )
                for (
                    student_id,
                    classroom_id,
                    teacher_id,
                    level,
                    tile_before_index,
                ), mistake_count in student_hotspots.items()
            ]
        )

        StudentWeekSpecialTileStats.objects.bulk_create(
            [
                StudentWeekSpecialTileStats(
                    student_id=student_id,
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    level=level,
                    special_tile_type=special_tile_type,
                    trigger_count=trigger_count,
                )
                for (
                    student_id,
                    classroom_id,
                    teacher_id,
                    level,
                    special_tile_type,
                ), trigger_count in student_special_tiles.items()
            ]
        )

        StudentWeekChainLengthStats.objects.bulk_create(
            [
                StudentWeekChainLengthStats(
                    student_id=student_id,
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    level=level,
                    chain_length=chain_length,
                    turn_count=turn_count,
                )
                for (
                    student_id,
                    classroom_id,
                    teacher_id,
                    level,
                    chain_length,
                ), turn_count in student_chain_lengths.items()
            ]
        )

        StudentWeekCardFamilyStats.objects.bulk_create(
            [
                StudentWeekCardFamilyStats(
                    student_id=student_id,
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    level=level,
                    card_family=card_family,
                    offered_count=values["offered_count"],
                    chosen_count=values["chosen_count"],
                    correct_count=values["correct_count"],
                    wrong_count=values["wrong_count"],
                    decision_time_sum_ms=values["decision_time_sum_ms"],
                    decision_time_count=values["decision_time_count"],
                    decision_time_sum_sq_ms=values["decision_time_sum_sq_ms"],
                    decision_time_min_ms=values["decision_time_min_ms"],
                    decision_time_max_ms=values["decision_time_max_ms"],
                )
                for (
                    student_id,
                    classroom_id,
                    teacher_id,
                    level,
                    card_family,
                ), values in student_card_families.items()
            ]
        )

        StudentWeekCardTypeStats.objects.bulk_create(
            [
                StudentWeekCardTypeStats(
                    student_id=student_id,
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    level=level,
                    card_type=card_type,
                    chosen_count=values["chosen_count"],
                    decision_time_sum_ms=values["decision_time_sum_ms"],
                    decision_time_count=values["decision_time_count"],
                    decision_time_sum_sq_ms=values["decision_time_sum_sq_ms"],
                    decision_time_min_ms=values["decision_time_min_ms"],
                    decision_time_max_ms=values["decision_time_max_ms"],
                    clipped_decision_time_sum_ms=values["clipped_decision_time_sum_ms"],
                    clipped_decision_time_sum_sq_ms=values[
                        "clipped_decision_time_sum_sq_ms"
                    ],
                    outlier_count=values["outlier_count"],
                )
                for (
                    student_id,
                    classroom_id,
                    teacher_id,
                    level,
                    card_type,
                ), values in student_card_types.items()
            ]
        )

        StudentWeekConditionalStats.objects.bulk_create(
            [
                StudentWeekConditionalStats(
                    student_id=student_id,
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    level=level,
                    conditional_kind=conditional_kind,
                    bucket_key=bucket_key,
                    total_count=values["total_count"],
                    correct_count=values["correct_count"],
                    else_count=values["else_count"],
                )
                for (
                    student_id,
                    classroom_id,
                    teacher_id,
                    level,
                    conditional_kind,
                    bucket_key,
                ), values in student_conditionals.items()
            ]
        )

        StudentWeekBackCardUsageStats.objects.bulk_create(
            [
                StudentWeekBackCardUsageStats(
                    student_id=student_id,
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    level=level,
                    place_before=place_before,
                    count=count,
                )
                for (
                    student_id,
                    classroom_id,
                    teacher_id,
                    level,
                    place_before,
                ), count in student_back_usage.items()
            ]
        )

        StudentWeekForeachContextStats.objects.bulk_create(
            [
                StudentWeekForeachContextStats(
                    student_id=student_id,
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    level=level,
                    with_opponent_count=values["with_opponent_count"],
                    without_opponent_count=values["without_opponent_count"],
                )
                for (
                    student_id,
                    classroom_id,
                    teacher_id,
                    level,
                ), values in student_foreach_context.items()
            ]
        )

        StudentWeekNumberChoiceStats.objects.bulk_create(
            [
                StudentWeekNumberChoiceStats(
                    student_id=student_id,
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    level=level,
                    chosen_number=chosen_number,
                    choice_count=values["choice_count"],
                    decision_time_sum_ms=values["decision_time_sum_ms"],
                    decision_time_count=values["decision_time_count"],
                    decision_time_sum_sq_ms=values["decision_time_sum_sq_ms"],
                    decision_time_min_ms=values["decision_time_min_ms"],
                    decision_time_max_ms=values["decision_time_max_ms"],
                )
                for (
                    student_id,
                    classroom_id,
                    teacher_id,
                    level,
                    chosen_number,
                ), values in student_number_choices.items()
            ]
        )

        ClassroomWeekStats.objects.bulk_create(
            [
                ClassroomWeekStats(
                    classroom_id=classroom_id,
                    teacher_id=teacher_id,
                    week_start=week_start,
                    student_count=classroom_student_counts.get(classroom_id, 0),
                    runs=values["runs"],
                    wins=values["wins"],
                    correct_moves=values["correct_moves"],
                    wrong_moves=values["wrong_moves"],
                    score_sum=values["score_sum"],
                    score_count=values["score_count"],
                    score_sum_sq=values["score_sum_sq"],
                    elapsed_sum_ms=values["elapsed_sum_ms"],
                    elapsed_count=values["elapsed_count"],
                    elapsed_sum_sq=values["elapsed_sum_sq"],
                )
                for (classroom_id, teacher_id), values in classroom_week.items()
            ]
        )

    return {
        "week_start": week_start,
        "week_end": week_end,
        "run_count": len(runs),
        "student_week_rows": len(student_week),
        "student_week_level_rows": len(student_level),
        "student_week_card_type_rows": len(student_card_types),
        "classroom_week_rows": len(classroom_week),
    }
