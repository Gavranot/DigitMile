import json
import logging
from typing import Union

import redis as redis_client
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from ninja import Router
from pydantic import TypeAdapter, ValidationError

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

# Single-pass Rust JSON parse + validation. Unity and canonical have disjoint
# required fields (userID vs student_id), so smart-mode union routing is
# unambiguous and the losing branch short-circuits before model_validators run.
_IngestAdapter: TypeAdapter[Union[UnityIngestPayload, CanonicalIngestPayload]] = TypeAdapter(
    Union[UnityIngestPayload, CanonicalIngestPayload]
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

    # Parse + validate in a single Rust pass (pydantic-core).
    raw_body = request.body
    try:
        payload = _IngestAdapter.validate_json(raw_body)
    except ValidationError as exc:
        errs = exc.errors()
        # pydantic-core surfaces malformed JSON as a json_invalid error; map it
        # back to the prior {"error": "Invalid JSON"} 400 response shape so any
        # client that checks that exact message keeps working.
        if errs and errs[0].get("type") == "json_invalid":
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        # Error path only: parse once for log enrichment. Happy path skips this.
        try:
            body_for_log = json.loads(raw_body)
            if not isinstance(body_for_log, dict):
                body_for_log = {}
        except (json.JSONDecodeError, ValueError):
            body_for_log = {}
        _log_run_ingest_event(
            logging.WARNING,
            "run_ingest_validation_failed",
            student_id=body_for_log.get("userID") or body_for_log.get("student_id"),
            run_id=body_for_log.get("run_id"),
            errors=errs,
        )
        return JsonResponse(
            {"error": "Validation failed", "details": errs},
            status=400,
        )

    if isinstance(payload, UnityIngestPayload):
        if not Student.objects.filter(pk=payload.userID).exists():
            return JsonResponse(
                {"error": "Validation failed", "details": {"userID": ["Student does not exist"]}},
                status=400,
            )
        data = normalize_unity_run_ingestion_payload(payload.model_dump())
    else:
        if not Student.objects.filter(pk=payload.student_id).exists():
            return JsonResponse(
                {"error": "Validation failed", "details": {"student_id": ["Student does not exist"]}},
                status=400,
            )
        data = payload.model_dump()

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
