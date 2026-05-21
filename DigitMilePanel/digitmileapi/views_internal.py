"""
Internal service-to-service endpoints. Authenticated by a shared secret
header (X-Internal-Token) loaded from settings.INTERNAL_API_TOKEN, NOT by
Django session/auth. Intended for the compactor cron container and similar
in-cluster callers that have no user identity.
"""

import hmac
import json
import logging
import os
import subprocess
import sys
from datetime import date, timedelta

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import WeeklyCompactionRun
from .weekly_rollups import week_start_for


logger = logging.getLogger(__name__)

MAX_WORKERS_CEILING = 8  # Hard cap regardless of caller input; PG conn budget.


def _check_internal_token(request):
    token = settings.INTERNAL_API_TOKEN
    if not token:
        # Empty/unset token means the endpoint is administratively closed.
        # Refuse rather than accidentally accepting an empty header.
        return False
    presented = request.headers.get("X-Internal-Token", "")
    return hmac.compare_digest(presented, token)


def _last_completed_week_start(today=None):
    """
    Return the Monday of the most-recently-completed gameplay week. If today
    is itself a Monday, the previous week is the most recently completed
    one. Aligns with how production callers will invoke compaction on the
    Monday immediately after a closed week.
    """
    today = today or date.today()
    # Snap today to its week's Monday, then step back 7 days.
    return week_start_for(today) - timedelta(days=7)


@csrf_exempt
@require_POST
def trigger_weekly_compaction(request):
    """
    POST /panel/api/internal/compaction/run-weekly/

    Headers:
      X-Internal-Token: <shared-secret>

    Body (JSON, all fields optional):
      {
        "week_start": "YYYY-MM-DD",  // defaults to last completed week
        "max_workers": 2,             // 1..MAX_WORKERS_CEILING, defaults to 2
        "dry_run": false              // defaults to false
      }

    Returns:
      202 {"status": "started", "week_start": "...", "compaction_id": N,
           "max_workers": N, "dry_run": bool}
      400 invalid input
      401 missing/wrong token
      409 already COMPACTED

    The compaction is spawned as a detached subprocess and runs out-of-band
    via `manage.py compact_weekly_runs --per-teacher --max-workers N`. Status
    is observable via the WeeklyCompactionRun row (PENDING → COMPACTED/FAILED).
    """
    if not _check_internal_token(request):
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return JsonResponse({"error": "body must be a JSON object"}, status=400)

    raw_week_start = body.get("week_start")
    if raw_week_start:
        try:
            requested = date.fromisoformat(raw_week_start)
        except (TypeError, ValueError):
            return JsonResponse(
                {"error": "week_start must be YYYY-MM-DD"}, status=400
            )
        week_start = week_start_for(requested)
    else:
        week_start = _last_completed_week_start()

    raw_max_workers = body.get("max_workers", 2)
    try:
        max_workers = int(raw_max_workers)
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "max_workers must be an integer"}, status=400
        )
    if max_workers < 1 or max_workers > MAX_WORKERS_CEILING:
        return JsonResponse(
            {
                "error": (
                    f"max_workers must be between 1 and "
                    f"{MAX_WORKERS_CEILING} (got {max_workers})"
                )
            },
            status=400,
        )

    dry_run = bool(body.get("dry_run", False))

    existing = WeeklyCompactionRun.objects.filter(week_start=week_start).first()
    if (
        existing is not None
        and existing.status == WeeklyCompactionRun.Status.COMPACTED
    ):
        return JsonResponse(
            {
                "error": "already compacted",
                "week_start": week_start.isoformat(),
                "compaction_id": existing.id,
            },
            status=409,
        )

    proc = _spawn_compaction_subprocess(week_start, max_workers, dry_run)

    logger.info(
        "trigger_weekly_compaction spawned compactor pid=%s week_start=%s "
        "max_workers=%s dry_run=%s",
        proc.pid,
        week_start.isoformat(),
        max_workers,
        dry_run,
    )

    return JsonResponse(
        {
            "status": "started",
            "week_start": week_start.isoformat(),
            "max_workers": max_workers,
            "dry_run": dry_run,
            "subprocess_pid": proc.pid,
            "compaction_id": existing.id if existing else None,
        },
        status=202,
    )


def _spawn_compaction_subprocess(week_start, max_workers, dry_run):
    # Resolve manage.py relative to settings.BASE_DIR so the subprocess works
    # under the gunicorn runtime regardless of cwd. Detach stdout/stderr to
    # the parent's so logs surface in the backend container, but don't wait.
    manage_py = os.path.join(settings.BASE_DIR, "manage.py")
    argv = [
        sys.executable,
        manage_py,
        "compact_weekly_runs",
        week_start.isoformat(),
        "--per-teacher",
        "--max-workers",
        str(max_workers),
    ]
    if dry_run:
        argv.append("--dry-run")
    # Inherit gunicorn worker stdio so compaction logs surface in the backend
    # container's docker logs (the management command logs progress via the
    # `logger` object + self.stdout.write). start_new_session=True puts the
    # child in its own process group so gunicorn worker recycling (SIGTERM)
    # does not cascade and kill an in-flight 30-60 min compaction.
    return subprocess.Popen(
        argv,
        start_new_session=True,
    )
