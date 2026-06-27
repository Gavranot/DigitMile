"""Tests for ingest durability: retry, durable Postgres fallback, and recovery.

These cover the guarantee that a validated run is never lost when Redis is
unavailable. The ingest endpoint (digitmileapi.ingest_router) retries the Redis
lpush a few times, and on continued failure writes the payload to the
PendingIngest table; the flush worker re-enqueues those rows once Redis recovers.

Redis is faked two ways:
  * fakeredis.FakeStrictRedis() for happy-path / recovery (a real in-memory list),
  * a Mock whose lpush raises RedisError to simulate an outage.

Canonical (snake_case) payloads are used because they carry an explicit run_id
(needed for idempotency assertions) and, by passing elapsed_ms without
run_ended_unix_ms, they bypass the recording-window check entirely.
"""

import json
from unittest import mock

import fakeredis
from django.conf import settings
from django.db import DatabaseError
from django.test import TestCase, override_settings
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient

from digitmileapi import ingest_router
from digitmileapi.management.commands.flush_ingest_buffer import Command as FlushCommand
from digitmileapi.models import (
    Classroom,
    PendingIngest,
    Run,
    School,
    Student,
    Teacher,
    TurnEvent,
)

KEY = settings.INGEST_BUFFER_REDIS_KEY
INGEST_URL = "/panel/api/runs/ingest/"


@override_settings(INGEST_REDIS_RETRY_BACKOFF_MS=0, INGEST_REDIS_MAX_RETRIES=3)
class IngestDurabilityBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name="Durability School",
            municipality="Skopje",
            region="Skopje",
            address="Durability Address 1",
            director_name="Durability Director",
            school_email="durability-school@example.com",
        )
        self.teacher = Teacher.objects.create(
            full_name="Teacher Durability",
            email="durability-teacher@example.com",
            status="APPROVED",
        )
        self.classroom = Classroom.objects.create(
            classroom_key="DURABLE-1",
            classroom_name="5-A",
            grade=5,
            teacher=self.teacher,
            school=self.school,
        )
        self.student = Student.objects.create(
            full_name="Student Durability",
            grade=5,
            classroom=self.classroom,
        )
        self.client = APIClient()
        self.fake = fakeredis.FakeStrictRedis()

    # --- helpers ---------------------------------------------------------

    def _payload(self, run_id="run_durtest_0001", student_id=None):
        """A minimal valid canonical run: 1 correct turn, place=2 (not a win),
        elapsed_ms provided so the recording-window check is skipped."""
        return {
            "run_id": run_id,
            "student_id": student_id or self.student.id,
            "level": 5,
            "score": 100,
            "place": 2,
            "elapsed_ms": 45000,
            "correct_moves": 1,
            "wrong_moves": 0,
            "game_map": [
                {"tileMapIndex": 0, "tileIndex": 0, "tileType": 0},
                {"tileMapIndex": 1, "tileIndex": 1, "tileType": 1},
            ],
            "turn_events": [
                {
                    "turn_index": 0,
                    "timestamp_played_unix_ms": 1762776001000,
                    "chosen_card": {
                        "type": "MoveX",
                        "data": "[CardData: tileType=, ifSign=, ifValue=, thenValue=1, elseValue=]",
                    },
                    "offered_cards": [],
                    "was_correct": True,
                    "tile_before_index": 0,
                    "tile_before_type": 0,
                    "tile_after_index": 1,
                    "place_before": 2,
                    "place_after": 2,
                    "card_decision_time_ms": 1500,
                    "offered_numbers": [],
                    "chosen_number": None,
                    "number_decision_time_ms": None,
                    "special_tile_triggers": [],
                }
            ],
        }

    def _post(self, payload):
        return self.client.post(INGEST_URL, payload, format="json")

    def _redis_up(self):
        """Patch the endpoint's Redis client with a working in-memory fake."""
        return mock.patch.object(ingest_router, "_redis", self.fake)

    def _redis_down(self, side_effect=None):
        """Patch the endpoint's Redis client with a Mock whose lpush fails."""
        broken = mock.Mock()
        broken.lpush.side_effect = side_effect or RedisConnectionError("redis down")
        return mock.patch.object(ingest_router, "_redis", broken), broken

    def _buffer_run_ids(self):
        return [json.loads(item)["run_id"] for item in self.fake.lrange(KEY, 0, -1)]


# =====================================================================
# Endpoint behaviour while Redis is UP
# =====================================================================
class IngestEndpointRedisUpTests(IngestDurabilityBase):
    def test_happy_path_queues_to_redis_and_returns_202(self):
        with self._redis_up():
            resp = self._post(self._payload())

        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["run_id"], "run_durtest_0001")
        self.assertEqual(self.fake.llen(KEY), 1)
        self.assertEqual(self._buffer_run_ids(), ["run_durtest_0001"])
        # Nothing should hit the durable fallback on the happy path.
        self.assertEqual(PendingIngest.objects.count(), 0)
        # The endpoint must not synchronously create the Run (the flusher does).
        self.assertEqual(Run.objects.count(), 0)

    def test_existing_run_short_circuits_before_buffer(self):
        Run.objects.create(
            id="run_durtest_0001",
            student=self.student,
            level=5,
            player_won=False,
            score=100,
            place=2,
            elapsed_ms=45000,
            correct_moves=1,
            wrong_moves=0,
        )
        with self._redis_up():
            resp = self._post(self._payload())

        self.assertEqual(resp.status_code, 200)
        self.assertIn("already", resp.json()["message"].lower())
        self.assertEqual(self.fake.llen(KEY), 0)
        self.assertEqual(PendingIngest.objects.count(), 0)

    def test_invalid_payload_is_not_buffered(self):
        bad = self._payload()
        bad["wrong_moves"] = 5  # contradicts the single correct turn
        with self._redis_up():
            resp = self._post(bad)

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.fake.llen(KEY), 0)
        self.assertEqual(PendingIngest.objects.count(), 0)

    def test_unknown_student_is_not_buffered(self):
        with self._redis_up():
            resp = self._post(self._payload(student_id="stu_missing000"))

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.fake.llen(KEY), 0)
        self.assertEqual(PendingIngest.objects.count(), 0)

    def test_cross_field_error_returns_serializable_400(self):
        # Regression: a cross-field (model-validator) failure used to 500 because
        # pydantic's error ctx (a raw ValueError) isn't JSON-serializable.
        bad = self._payload()
        bad["wrong_moves"] = 5  # contradicts the single correct turn
        with self._redis_up():
            resp = self._post(bad)

        self.assertEqual(resp.status_code, 400)
        body = resp.json()  # must parse — this is the actual regression guard
        self.assertEqual(body["error"], "Validation failed")
        self.assertTrue(
            any("wrong_moves mismatch" in d["msg"] for d in body["details"])
        )

    def test_malformed_json_returns_400_and_is_not_buffered(self):
        with self._redis_up():
            resp = self.client.post(
                INGEST_URL, data="this is not json", content_type="application/json"
            )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "Invalid JSON")
        self.assertEqual(self.fake.llen(KEY), 0)
        self.assertEqual(PendingIngest.objects.count(), 0)


# =====================================================================
# Endpoint behaviour while Redis is DOWN (fallback path)
# =====================================================================
class IngestEndpointRedisDownTests(IngestDurabilityBase):
    def test_redis_down_falls_back_to_db_and_returns_202(self):
        patcher, broken = self._redis_down()
        with patcher:
            resp = self._post(self._payload())

        self.assertEqual(resp.status_code, 202)
        # Retried up to the configured limit before giving up.
        self.assertEqual(broken.lpush.call_count, settings.INGEST_REDIS_MAX_RETRIES)
        # Durable fallback row written, payload preserved verbatim.
        self.assertEqual(PendingIngest.objects.count(), 1)
        row = PendingIngest.objects.get(run_id="run_durtest_0001")
        self.assertEqual(row.payload["student_id"], self.student.id)
        self.assertEqual(row.payload["score"], 100)

    def test_transient_failure_then_success_does_not_fall_back(self):
        # Fail twice, succeed on the third attempt.
        patcher, broken = self._redis_down(
            side_effect=[RedisConnectionError("blip"), RedisConnectionError("blip"), 1]
        )
        with patcher:
            resp = self._post(self._payload())

        self.assertEqual(resp.status_code, 202)
        self.assertEqual(broken.lpush.call_count, 3)
        self.assertEqual(PendingIngest.objects.count(), 0)

    def test_redis_and_db_down_returns_503(self):
        patcher, _ = self._redis_down()
        with patcher, mock.patch.object(
            ingest_router.PendingIngest.objects,
            "get_or_create",
            side_effect=DatabaseError("db unavailable"),
        ):
            resp = self._post(self._payload())

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(PendingIngest.objects.count(), 0)

    def test_duplicate_fallback_is_idempotent(self):
        patcher, _ = self._redis_down()
        with patcher:
            self._post(self._payload())
            self._post(self._payload())  # same run_id, Redis still down

        self.assertEqual(
            PendingIngest.objects.filter(run_id="run_durtest_0001").count(), 1
        )


# =====================================================================
# Retry helper unit tests
# =====================================================================
class RetryHelperTests(IngestDurabilityBase):
    def test_returns_true_and_enqueues_on_success(self):
        with self._redis_up():
            ok = ingest_router._enqueue_to_redis_with_retry(
                json.dumps(self._payload()), run_id="r", student_id="s"
            )
        self.assertTrue(ok)
        self.assertEqual(self.fake.llen(KEY), 1)

    def test_returns_false_after_exhausting_retries(self):
        patcher, broken = self._redis_down()
        with patcher:
            ok = ingest_router._enqueue_to_redis_with_retry(
                "{}", run_id="r", student_id="s"
            )
        self.assertFalse(ok)
        self.assertEqual(broken.lpush.call_count, settings.INGEST_REDIS_MAX_RETRIES)

    def test_succeeds_before_exhausting_retries(self):
        patcher, broken = self._redis_down(
            side_effect=[RedisConnectionError("blip"), 1]
        )
        with patcher:
            ok = ingest_router._enqueue_to_redis_with_retry(
                "{}", run_id="r", student_id="s"
            )
        self.assertTrue(ok)
        self.assertEqual(broken.lpush.call_count, 2)


# =====================================================================
# Flusher fallback-drain tests
# =====================================================================
class FlusherDrainTests(IngestDurabilityBase):
    def _make_pending(self, run_id):
        return PendingIngest.objects.create(
            run_id=run_id, payload=self._payload(run_id=run_id)
        )

    def test_drain_reenqueues_and_deletes_rows(self):
        self._make_pending("run_a")
        self._make_pending("run_b")

        FlushCommand()._drain_db_fallback(self.fake, settings.INGEST_BUFFER_BATCH_SIZE)

        self.assertEqual(PendingIngest.objects.count(), 0)
        self.assertEqual(self.fake.llen(KEY), 2)
        self.assertCountEqual(self._buffer_run_ids(), ["run_a", "run_b"])

    def test_drain_when_redis_still_down_keeps_rows(self):
        self._make_pending("run_a")
        broken = mock.Mock()
        broken.lpush.side_effect = RedisConnectionError("still down")

        # Must not raise, and the durable row must survive for the next cycle.
        FlushCommand()._drain_db_fallback(broken, settings.INGEST_BUFFER_BATCH_SIZE)

        self.assertEqual(PendingIngest.objects.filter(run_id="run_a").count(), 1)

    def test_drain_respects_batch_size(self):
        self._make_pending("run_a")
        self._make_pending("run_b")
        self._make_pending("run_c")

        FlushCommand()._drain_db_fallback(self.fake, 2)

        self.assertEqual(PendingIngest.objects.count(), 1)
        self.assertEqual(self.fake.llen(KEY), 2)

    def test_drain_empty_table_is_noop(self):
        FlushCommand()._drain_db_fallback(self.fake, settings.INGEST_BUFFER_BATCH_SIZE)
        self.assertEqual(self.fake.llen(KEY), 0)


# =====================================================================
# End-to-end: outage -> durable fallback -> recovery -> Run persisted
# =====================================================================
class IngestRecoveryEndToEndTests(IngestDurabilityBase):
    def test_outage_then_recovery_persists_run_with_no_loss(self):
        # 1) Redis is down when the run arrives -> durable fallback, no Run yet.
        patcher, _ = self._redis_down()
        with patcher:
            resp = self._post(self._payload())
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(PendingIngest.objects.count(), 1)
        self.assertEqual(Run.objects.count(), 0)

        # 2) Redis recovers: the flusher drains the fallback back into the buffer.
        cmd = FlushCommand()
        cmd._drain_db_fallback(self.fake, settings.INGEST_BUFFER_BATCH_SIZE)
        self.assertEqual(PendingIngest.objects.count(), 0)
        self.assertEqual(self.fake.llen(KEY), 1)

        # 3) The normal flush turns the buffered payload into a real Run.
        cmd._flush_batch(self.fake, settings.INGEST_BUFFER_BATCH_SIZE)

        self.assertTrue(Run.objects.filter(id="run_durtest_0001").exists())
        self.assertEqual(TurnEvent.objects.filter(run_id="run_durtest_0001").count(), 1)
        self.assertEqual(PendingIngest.objects.count(), 0)
        self.assertEqual(self.fake.llen(KEY), 0)
