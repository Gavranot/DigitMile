import hashlib
import json
from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.utils import timezone

from .weekly_rollups import week_end_for, week_start_for


MAX_GAME_DURATION_MS = 7_200_000
RECORDING_CLOSE_WEEKDAY = 4
RECORDING_CLOSE_HOUR = 20


def unix_ms_to_datetime(unix_ms):
    return datetime.fromtimestamp(unix_ms / 1000.0, tz=dt_timezone.utc)


def clamp_elapsed_ms(start_unix_ms, end_unix_ms):
    elapsed_ms = end_unix_ms - start_unix_ms
    if elapsed_ms < 0:
        return 0
    if elapsed_ms > MAX_GAME_DURATION_MS:
        return MAX_GAME_DURATION_MS
    return elapsed_ms


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def derive_run_id_from_unity_payload(student_id, run_data):
    existing_run_id = str(run_data.get("runId") or "").strip()
    if existing_run_id:
        return existing_run_id

    canonical_payload = {
        "student_id": student_id,
        "level": run_data.get("level"),
        "score": run_data.get("score"),
        "place": run_data.get("place"),
        "correct_moves": run_data.get("correct_moves"),
        "wrong_moves": run_data.get("wrong_moves"),
        "runStartedUnixMs": run_data.get("runStartedUnixMs"),
        "runEndedUnixMs": run_data.get("runEndedUnixMs"),
        "gameMap": run_data.get("gameMap"),
        "turns": run_data.get("turns", []),
    }
    digest = hashlib.sha256(_canonical_json(canonical_payload).encode("utf-8")).hexdigest()
    return f"run_{digest[:32]}"


def normalize_unity_run_ingestion_payload(validated_data):
    run_data = validated_data["run"]
    student_id = validated_data["userID"]

    normalized_turns = []
    for turn_data in run_data.get("turns", []):
        normalized_turns.append(
            {
                "turn_index": turn_data["turnIndex"],
                "timestamp_played_unix_ms": turn_data["timestampPlayedUnixMs"],
                "chosen_card": turn_data["chosenCard"],
                "offered_cards": turn_data.get("offeredCards", []),
                "was_correct": turn_data["wasCorrect"],
                "tile_before_index": turn_data["tileBefore"]["tileMapIndex"],
                "tile_before_type": turn_data["tileBefore"]["tileIndex"],
                "tile_after_index": turn_data["playerPositionAfter"]["tileMapIndex"],
                "place_before": turn_data["playerPositionBefore"]["placeRelativeToBots"],
                "place_after": turn_data["playerPositionAfter"]["placeRelativeToBots"],
                "bot_positions_before": turn_data.get("botPositionsBefore", []),
                "bot_positions_after": turn_data.get("botPositionsAfter", []),
                "card_decision_time_ms": turn_data["cardDecisionTimeMs"],
                "offered_numbers": turn_data.get("offeredNumbers", []),
                "chosen_number": turn_data.get("chosenNumber"),
                "number_decision_time_ms": turn_data.get("numberDecisionTimeMs"),
                "special_tile_triggers": [
                    {
                        "chain_index": trigger_data["chainIndex"],
                        "special_tile_index": trigger_data["specialTile"]["tileMapIndex"],
                        "special_tile_type": trigger_data["specialTile"]["tileIndex"],
                        "effect_delta_tiles": trigger_data["effectDeltaTiles"],
                        "target_tile_index": trigger_data["positionAfterEffect"]["tileMapIndex"],
                        "target_tile_type": 0,
                        "place_before": trigger_data["positionOnSpecialTile"]["placeRelativeToBots"],
                        "place_after": trigger_data["positionAfterEffect"]["placeRelativeToBots"],
                    }
                    for trigger_data in turn_data.get("specialTileTriggers", [])
                ],
            }
        )

    place = run_data["place"]
    run_started_unix_ms = run_data["runStartedUnixMs"]
    run_ended_unix_ms = run_data["runEndedUnixMs"]

    return {
        "run_id": derive_run_id_from_unity_payload(student_id, run_data),
        "student_id": student_id,
        "level": run_data["level"],
        "place": place,
        # Derived fields — computed here so the canonical serializer pass can be
        # skipped entirely for Unity payloads (the Unity serializer already validated
        # correct_moves/wrong_moves/place consistency in its own validate()).
        "player_won": place == 1,
        "elapsed_ms": clamp_elapsed_ms(run_started_unix_ms, run_ended_unix_ms),
        "score": run_data["score"],
        "correct_moves": run_data["correct_moves"],
        "wrong_moves": run_data["wrong_moves"],
        "run_started_unix_ms": run_started_unix_ms,
        "run_ended_unix_ms": run_ended_unix_ms,
        "game_map": run_data["gameMap"]["mapTiles"],
        "map_version": "1",
        "bot_version": "1",
        "rng_seed": None,
        "turn_events": normalized_turns,
    }


def week_close_datetime_for(week_start):
    close_date = week_start + timedelta(days=RECORDING_CLOSE_WEEKDAY)
    return timezone.make_aware(
        datetime.combine(close_date, time(hour=RECORDING_CLOSE_HOUR)),
        timezone.get_current_timezone(),
    )


def get_recording_window_status_for_run_finish(run_finished_at, reference_time=None):
    if timezone.is_naive(run_finished_at):
        run_finished_at = timezone.make_aware(
            run_finished_at,
            timezone.get_current_timezone(),
        )

    current_time = reference_time or timezone.now()
    if timezone.is_naive(current_time):
        current_time = timezone.make_aware(current_time, timezone.get_current_timezone())

    localized_finished_at = timezone.localtime(
        run_finished_at,
        timezone.get_current_timezone(),
    )
    localized_current_time = timezone.localtime(
        current_time,
        timezone.get_current_timezone(),
    )
    week_start = week_start_for(localized_finished_at.date())
    close_at = week_close_datetime_for(week_start)

    return {
        "run_finished_at": localized_finished_at,
        "week_start": week_start,
        "week_end": week_end_for(week_start),
        "close_at": close_at,
        "is_open": localized_current_time < close_at,
    }
