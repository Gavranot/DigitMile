"""
Unit tests for the internal service-to-service endpoints (shared-secret auth).

The compaction trigger endpoint must:
  - 401 when the X-Internal-Token header is missing or wrong
  - 401 when INTERNAL_API_TOKEN is empty (administratively closed)
  - 400 on malformed JSON / invalid week_start / out-of-range max_workers
  - 409 when the requested week is already COMPACTED
  - 202 on the happy path, with a detached subprocess spawned

The subprocess.Popen call site is mocked so tests don't actually fork
`manage.py compact_weekly_runs`. The orchestration logic in
compact_weekly_runs itself is covered by test_compact_weekly_runs_parallel
and test_rollup_accuracy.
"""

import json
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase, Client, override_settings

from .models import WeeklyCompactionRun
from .weekly_rollups import week_start_for


TRIGGER_URL = "/panel/api/internal/compaction/run-weekly/"
VALID_TOKEN = "test-shared-secret-do-not-use-in-prod"


class FakeProc:
    def __init__(self, pid=12345):
        self.pid = pid


@override_settings(INTERNAL_API_TOKEN=VALID_TOKEN)
class TriggerWeeklyCompactionAuthTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_missing_token_returns_401(self):
        response = self.client.post(
            TRIGGER_URL,
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_wrong_token_returns_401(self):
        response = self.client.post(
            TRIGGER_URL,
            data=json.dumps({}),
            content_type="application/json",
            HTTP_X_INTERNAL_TOKEN="not-the-right-token",
        )
        self.assertEqual(response.status_code, 401)

    def test_get_not_allowed(self):
        response = self.client.get(
            TRIGGER_URL, HTTP_X_INTERNAL_TOKEN=VALID_TOKEN
        )
        self.assertEqual(response.status_code, 405)


@override_settings(INTERNAL_API_TOKEN="")
class TriggerWeeklyCompactionDisabledTest(TestCase):
    """Empty INTERNAL_API_TOKEN administratively closes the endpoint."""

    def test_empty_token_setting_refuses_all_requests(self):
        client = Client()
        response = client.post(
            TRIGGER_URL,
            data=json.dumps({}),
            content_type="application/json",
            HTTP_X_INTERNAL_TOKEN="",
        )
        self.assertEqual(response.status_code, 401)


@override_settings(INTERNAL_API_TOKEN=VALID_TOKEN)
class TriggerWeeklyCompactionValidationTest(TestCase):
    def setUp(self):
        self.client = Client()

    def _post(self, body):
        return self.client.post(
            TRIGGER_URL,
            data=body if isinstance(body, (str, bytes)) else json.dumps(body),
            content_type="application/json",
            HTTP_X_INTERNAL_TOKEN=VALID_TOKEN,
        )

    def test_invalid_json_returns_400(self):
        response = self._post("{not valid json")
        self.assertEqual(response.status_code, 400)

    def test_non_object_body_returns_400(self):
        response = self._post(json.dumps([1, 2, 3]))
        self.assertEqual(response.status_code, 400)

    def test_invalid_week_start_returns_400(self):
        response = self._post({"week_start": "not-a-date"})
        self.assertEqual(response.status_code, 400)

    def test_max_workers_below_minimum_returns_400(self):
        with mock.patch(
            "digitmileapi.views_internal._spawn_compaction_subprocess",
            return_value=FakeProc(),
        ):
            response = self._post({"max_workers": 0})
        self.assertEqual(response.status_code, 400)

    def test_max_workers_above_ceiling_returns_400(self):
        with mock.patch(
            "digitmileapi.views_internal._spawn_compaction_subprocess",
            return_value=FakeProc(),
        ):
            response = self._post({"max_workers": 99})
        self.assertEqual(response.status_code, 400)


@override_settings(INTERNAL_API_TOKEN=VALID_TOKEN)
class TriggerWeeklyCompactionHappyPathTest(TestCase):
    def setUp(self):
        self.client = Client()

    def _post(self, body):
        return self.client.post(
            TRIGGER_URL,
            data=json.dumps(body),
            content_type="application/json",
            HTTP_X_INTERNAL_TOKEN=VALID_TOKEN,
        )

    def test_defaults_week_start_to_last_completed_week(self):
        captured = {}

        def fake_spawn(week_start, max_workers, dry_run):
            captured["week_start"] = week_start
            captured["max_workers"] = max_workers
            captured["dry_run"] = dry_run
            return FakeProc()

        with mock.patch(
            "digitmileapi.views_internal._spawn_compaction_subprocess",
            side_effect=fake_spawn,
        ):
            response = self._post({})

        self.assertEqual(response.status_code, 202)
        # Default week_start is the Monday of the week before this week.
        expected = week_start_for(date.today()) - timedelta(days=7)
        self.assertEqual(captured["week_start"], expected)
        self.assertEqual(captured["max_workers"], 2)
        self.assertFalse(captured["dry_run"])

    def test_accepts_explicit_week_start_and_overrides(self):
        captured = {}

        def fake_spawn(week_start, max_workers, dry_run):
            captured["week_start"] = week_start
            captured["max_workers"] = max_workers
            captured["dry_run"] = dry_run
            return FakeProc(pid=99999)

        with mock.patch(
            "digitmileapi.views_internal._spawn_compaction_subprocess",
            side_effect=fake_spawn,
        ):
            response = self._post(
                {
                    "week_start": "2025-09-10",  # Wednesday
                    "max_workers": 3,
                    "dry_run": True,
                }
            )

        self.assertEqual(response.status_code, 202)
        body = response.json()
        # week_start_for snaps to the containing Monday (2025-09-08).
        self.assertEqual(body["week_start"], "2025-09-08")
        self.assertEqual(captured["week_start"], date(2025, 9, 8))
        self.assertEqual(captured["max_workers"], 3)
        self.assertTrue(captured["dry_run"])
        self.assertEqual(body["subprocess_pid"], 99999)

    def test_returns_409_when_already_compacted(self):
        target_week = week_start_for(date.today()) - timedelta(days=7)
        WeeklyCompactionRun.objects.create(
            week_start=target_week,
            week_end=target_week + timedelta(days=6),
            status=WeeklyCompactionRun.Status.COMPACTED,
        )

        with mock.patch(
            "digitmileapi.views_internal._spawn_compaction_subprocess",
            return_value=FakeProc(),
        ) as spawn_mock:
            response = self._post({})

        self.assertEqual(response.status_code, 409)
        spawn_mock.assert_not_called()

    def test_does_not_block_when_pending_record_exists(self):
        """A previous PENDING/FAILED row should not block a fresh trigger.
        Compaction is idempotent (re-running a pending week is the recovery
        path), so the endpoint allows it. Only COMPACTED is final."""
        target_week = week_start_for(date.today()) - timedelta(days=7)
        WeeklyCompactionRun.objects.create(
            week_start=target_week,
            week_end=target_week + timedelta(days=6),
            status=WeeklyCompactionRun.Status.PENDING,
        )

        with mock.patch(
            "digitmileapi.views_internal._spawn_compaction_subprocess",
            return_value=FakeProc(),
        ) as spawn_mock:
            response = self._post({})

        self.assertEqual(response.status_code, 202)
        spawn_mock.assert_called_once()
