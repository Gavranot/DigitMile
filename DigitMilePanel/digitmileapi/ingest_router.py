import json
import logging

import redis as redis_client
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from ninja import Router
from pydantic import ValidationError

from .ingest_schemas import CanonicalIngestPayload, UnityIngestPayload
from .models import Run, Student
from .run_ingestion import (
    get_recording_window_status_for_run_finish,
    normalize_unity_run_ingestion_payload,
    unix_ms_to_datetime,
)
from .views import _log_run_ingest_event

# Redis connection for the ingest write buffer (same instance as Django cache)
_redis = redis_client.from_url(settings.CACHES["default"]["LOCATION"])

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

    # Push validated payload to Redis write buffer
    _redis.lpush(settings.INGEST_BUFFER_REDIS_KEY, json.dumps(data))

    _log_run_ingest_event(
        logging.INFO,
        "run_ingest_queued",
        run_id=run_id,
        student_id=data["student_id"],
    )

    return JsonResponse(
        {"message": "Run accepted", "run_id": str(run_id)},
        status=202,
    )
