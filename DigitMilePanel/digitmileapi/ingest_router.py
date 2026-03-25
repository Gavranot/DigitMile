import json
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from ninja import Router
from pydantic import ValidationError

from .ingest_schemas import CanonicalIngestPayload, UnityIngestPayload
from .models import Run, SpecialTileTrigger, Student, TurnEvent
from .run_ingestion import (
    get_recording_window_status_for_run_finish,
    normalize_unity_run_ingestion_payload,
    unix_ms_to_datetime,
)
from .views import (
    _extract_card_metadata,
    _log_run_ingest_event,
    _normalize_cards_for_ingestion,
)

logger = logging.getLogger(__name__)

router = Router()


def _looks_like_unity_payload(data: object) -> bool:
    return (
        isinstance(data, dict)
        and "run" in data
        and ("userID" in data or "classroomKey" in data or "user" in data)
    )


def _parse_benchmark_reference_time(request):
    """Returns (datetime | None, JsonResponse | None)."""
    if not getattr(settings, "BENCHMARK_TIME_OVERRIDE_ENABLED", False):
        return None, None
    header = request.headers.get("X-Benchmark-Reference-Time")
    if not header:
        return None, None
    parsed = parse_datetime(header)
    if parsed is None:
        return None, JsonResponse(
            {"error": "Invalid X-Benchmark-Reference-Time header; expected ISO-8601 datetime."},
            status=400,
        )
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed, None


@router.post("/runs/ingest/", auth=None)
def ingest_run(request):
    # Benchmark time override header
    benchmark_reference_time, err = _parse_benchmark_reference_time(request)
    if err is not None:
        _log_run_ingest_event(
            logging.WARNING,
            "run_ingest_invalid_benchmark_reference_time",
            header_value=request.headers.get("X-Benchmark-Reference-Time"),
        )
        return err

    # Parse body
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Validate and normalise to canonical dict
    if _looks_like_unity_payload(body):
        try:
            unity_payload = UnityIngestPayload.model_validate(body)
        except ValidationError as exc:
            _log_run_ingest_event(
                logging.WARNING,
                "run_ingest_validation_failed",
                student_id=body.get("userID"),
                errors=exc.errors(),
            )
            return JsonResponse(
                {"error": "Validation failed", "details": exc.errors()},
                status=400,
            )
        if not Student.objects.filter(pk=unity_payload.userID).exists():
            return JsonResponse(
                {"error": "Validation failed", "details": {"userID": ["Student does not exist"]}},
                status=400,
            )
        data = normalize_unity_run_ingestion_payload(unity_payload.model_dump())
    else:
        try:
            canonical = CanonicalIngestPayload.model_validate(body)
        except ValidationError as exc:
            _log_run_ingest_event(
                logging.WARNING,
                "run_ingest_validation_failed",
                student_id=body.get("student_id"),
                run_id=body.get("run_id"),
                errors=exc.errors(),
            )
            return JsonResponse(
                {"error": "Validation failed", "details": exc.errors()},
                status=400,
            )
        if not Student.objects.filter(pk=canonical.student_id).exists():
            return JsonResponse(
                {"error": "Validation failed", "details": {"student_id": ["Student does not exist"]}},
                status=400,
            )
        data = canonical.model_dump()

    run_id = data["run_id"]

    # Idempotency check
    if Run.objects.filter(id=run_id).exists():
        _log_run_ingest_event(
            logging.INFO,
            "run_ingest_duplicate",
            run_id=run_id,
            student_id=data.get("student_id"),
            reason="existing_run_id",
        )
        return JsonResponse(
            {"message": "Run already ingested", "run_id": str(run_id)},
            status=200,
        )

    # Recording window check
    recording_window = None
    run_ended_unix_ms = data.get("run_ended_unix_ms")
    if run_ended_unix_ms is not None:
        recording_window = get_recording_window_status_for_run_finish(
            unix_ms_to_datetime(run_ended_unix_ms),
            reference_time=benchmark_reference_time,
        )
        if not recording_window["is_open"]:
            _log_run_ingest_event(
                logging.WARNING,
                "run_ingest_closed_week_rejected",
                run_id=run_id,
                student_id=data.get("student_id"),
                week_start=str(recording_window["week_start"]),
                close_at=recording_window["close_at"].isoformat(),
                run_finished_at=recording_window["run_finished_at"].isoformat(),
            )
            return JsonResponse(
                {
                    "error": "Statistics recording for this week is closed until the next week.",
                    "run_id": str(run_id),
                    "week_start": str(recording_window["week_start"]),
                    "recording_closed_at": recording_window["close_at"].isoformat(),
                },
                status=409,
            )

    # Persist
    try:
        with transaction.atomic():
            run = Run.objects.create(
                id=run_id,
                student_id=data["student_id"],
                level=data["level"],
                player_won=data["player_won"],
                score=data["score"],
                place=data.get("place", 1 if data["player_won"] else 4),
                elapsed_ms=data["elapsed_ms"],
                correct_moves=data["correct_moves"],
                wrong_moves=data["wrong_moves"],
                game_map=data.get("game_map", []),
                map_version=data.get("map_version", "1"),
                bot_version=data.get("bot_version", "1"),
                rng_seed=data.get("rng_seed"),
            )

            turn_events_to_create = []
            turn_event_triggers_map = {}

            for event_data in data.get("turn_events", []):
                timestamp_played = unix_ms_to_datetime(event_data["timestamp_played_unix_ms"])
                chosen_card, offered_cards = _normalize_cards_for_ingestion(
                    event_data.get("chosen_card"), event_data.get("offered_cards")
                )
                chosen_card_type, chosen_card_family, chosen_card_tile_type = (
                    _extract_card_metadata(chosen_card)
                )

                turn_event = TurnEvent(
                    run=run,
                    turn_index=event_data["turn_index"],
                    timestamp_played=timestamp_played,
                    chosen_card=chosen_card,
                    chosen_card_type=chosen_card_type,
                    chosen_card_family=chosen_card_family,
                    chosen_card_tile_type=chosen_card_tile_type,
                    offered_cards=offered_cards,
                    was_correct=event_data["was_correct"],
                    tile_before_index=event_data["tile_before_index"],
                    tile_before_type=event_data["tile_before_type"],
                    tile_after_index=event_data["tile_after_index"],
                    place_before=event_data["place_before"],
                    place_after=event_data["place_after"],
                    bot_positions_before=event_data.get("bot_positions_before", []),
                    bot_positions_after=event_data.get("bot_positions_after", []),
                    card_decision_time_ms=event_data["card_decision_time_ms"],
                    offered_numbers=event_data.get("offered_numbers", []),
                    chosen_number=event_data.get("chosen_number"),
                    number_decision_time_ms=event_data.get("number_decision_time_ms"),
                )
                turn_events_to_create.append(turn_event)

                triggers = event_data.get("special_tile_triggers", [])
                if triggers:
                    turn_event_triggers_map[event_data["turn_index"]] = triggers

            created_turn_events = TurnEvent.objects.bulk_create(turn_events_to_create)
            turn_index_to_event = {e.turn_index: e for e in created_turn_events}

            triggers_to_create = []
            for turn_index, triggers in turn_event_triggers_map.items():
                turn_event = turn_index_to_event[turn_index]
                for trigger_data in triggers:
                    triggers_to_create.append(
                        SpecialTileTrigger(
                            turn=turn_event,
                            chain_index=trigger_data["chain_index"],
                            special_tile_index=trigger_data["special_tile_index"],
                            special_tile_type=trigger_data["special_tile_type"],
                            effect_delta_tiles=trigger_data["effect_delta_tiles"],
                            target_tile_index=trigger_data["target_tile_index"],
                            target_tile_type=trigger_data["target_tile_type"],
                            place_before=trigger_data["place_before"],
                            place_after=trigger_data["place_after"],
                        )
                    )

            if triggers_to_create:
                SpecialTileTrigger.objects.bulk_create(triggers_to_create)

            _log_run_ingest_event(
                logging.INFO,
                "run_ingest_accept",
                run_id=run_id,
                student_id=data["student_id"],
                place=run.place,
                player_won=run.player_won,
                week_start=str(recording_window["week_start"]) if recording_window else None,
                turn_events_count=len(created_turn_events),
                triggers_count=len(triggers_to_create),
            )

            return JsonResponse(
                {
                    "message": "Run ingested successfully",
                    "run_id": str(run_id),
                    "turn_events_count": len(created_turn_events),
                    "triggers_count": len(triggers_to_create),
                },
                status=201,
            )

    except IntegrityError as exc:
        if "duplicate key" in str(exc).lower() or "unique constraint" in str(exc).lower():
            logger.warning(f"Race condition detected for run {run_id}, returning 200")
            _log_run_ingest_event(
                logging.WARNING,
                "run_ingest_duplicate",
                run_id=run_id,
                student_id=data.get("student_id"),
                reason="race_condition_duplicate_key",
            )
            return JsonResponse(
                {"message": "Run already ingested (race condition)", "run_id": str(run_id)},
                status=200,
            )
        logger.error(f"Integrity error ingesting run {run_id}: {exc}")
        return JsonResponse(
            {"error": "Database integrity error", "details": str(exc)},
            status=409,
        )

    except Exception as exc:
        logger.exception(f"Error ingesting run {run_id}: {exc}")
        return JsonResponse(
            {"error": "Internal server error while saving run data"},
            status=500,
        )
