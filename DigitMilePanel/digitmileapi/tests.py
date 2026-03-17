import json
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.db import IntegrityError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (
    ClassroomWeekStats,
    Classroom,
    ReplayArchive,
    Run,
    School,
    SpecialTileTrigger,
    Student,
    StudentWeekCardFamilyStats,
    StudentWeekCardTypeStats,
    StudentWeekConditionalStats,
    StudentWeekHotspotStats,
    StudentWeekLevelStats,
    StudentWeekNumberChoiceStats,
    StudentWeekSpecialTileStats,
    StudentRunBucketTrend,
    StudentWeekStats,
    Teacher,
    TurnEvent,
    WeeklyCompactionRun,
)
from .run_ingestion import get_recording_window_status_for_run_finish
from .run_bucket_trends import get_student_run_bucket_points, rebuild_run_bucket_trends
from .serializers import RunIngestionSerializer
from .replay_archives import (
    get_replay_payload_for_run,
    load_archive_payload,
    verify_replay_archive,
    write_replay_archive,
)
from .rollup_analytics import (
    bag_conditional_accuracy_by_comparator_by_level,
    card_accuracy_by_family_by_level,
    decision_time_by_card_type,
    number_choice_distribution_by_level,
    offer_choice_share_by_family,
    tile_conditional_accuracy_by_tile_type_by_level,
)
from .weekly_rollups import (
    average_from_sum_count,
    clip_decision_time_ms,
    sample_stddev_from_stats,
    week_end_for,
    week_start_for,
)
from .weekly_aggregation import aggregate_weekly_rollups
from .views import _build_student_dashboard_info


class WeeklyRollupUtilityTests(TestCase):
    def test_week_boundaries_use_monday_start(self):
        value = date(2026, 3, 11)

        self.assertEqual(week_start_for(value), date(2026, 3, 9))
        self.assertEqual(week_end_for(value), date(2026, 3, 15))

    def test_sufficient_statistics_helpers(self):
        self.assertEqual(average_from_sum_count(30, 3), 10)
        self.assertEqual(average_from_sum_count(30, 0), 0)
        self.assertAlmostEqual(sample_stddev_from_stats(15, 77, 3), 1.0)


class RunIngestionTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name="Ingestion School",
            municipality="Skopje",
            region="Skopje",
            address="Ingestion Address 1",
            director_name="Ingestion Director",
            school_email="ingestion-school@example.com",
        )
        self.teacher = Teacher.objects.create(
            full_name="Teacher Ingestion",
            email="ingestion-teacher@example.com",
            status="APPROVED",
        )
        self.classroom = Classroom.objects.create(
            classroom_key="INGEST-1234",
            classroom_name="5-A",
            grade=5,
            teacher=self.teacher,
            school=self.school,
        )
        self.student = Student.objects.create(
            full_name="Student Ingestion",
            grade=5,
            classroom=self.classroom,
        )
        self.client = APIClient()

    def _unity_payload(self):
        return {
            "classroomKey": self.classroom.classroom_key,
            "user": self.student.full_name,
            "userID": self.student.id,
            "run": {
                "runId": "",
                "level": 5,
                "score": 350,
                "place": 1,
                "correct_moves": 2,
                "wrong_moves": 1,
                "runStartedUnixMs": 1762776000000,
                "runEndedUnixMs": 1762776045000,
                "gameMap": {
                    "mapTiles": [
                        {
                            "tileMapIndex": 0,
                            "tileIndex": 0,
                            "tileType": 0,
                            "special": "normal",
                            "special_delta": 0,
                        },
                        {
                            "tileMapIndex": 1,
                            "tileIndex": 1,
                            "tileType": 1,
                            "special": "normal",
                            "special_delta": 0,
                        },
                        {
                            "tileMapIndex": 2,
                            "tileIndex": 5,
                            "tileType": 5,
                            "special": "skateboard",
                            "special_delta": 5,
                        },
                    ]
                },
                "turns": [
                    {
                        "runId": "",
                        "turnIndex": 0,
                        "timestampPlayedUnixMs": 1762776001000,
                        "chosenCard": {
                            "type": "MoveX",
                            "data": "[CardData: tileType=, ifSign=, ifValue=, thenValue=, elseValue=]",
                        },
                        "wasCorrect": True,
                        "offeredCards": [
                            {
                                "type": "MoveX",
                                "data": "[CardData: tileType=, ifSign=, ifValue=, thenValue=, elseValue=]",
                            },
                            {
                                "type": "IfBagEqualXMoveYElseMoveZ",
                                "data": "[CardData: tileType=, ifSign==, ifValue=3, thenValue=2, elseValue=1]",
                            },
                        ],
                        "playerPositionBefore": {
                            "placeRelativeToBots": 2,
                            "tileMapIndex": 0,
                        },
                        "playerPositionAfter": {
                            "placeRelativeToBots": 1,
                            "tileMapIndex": 1,
                        },
                        "botPositionsBefore": [],
                        "botPositionsAfter": [],
                        "tileBefore": {
                            "tileMapIndex": 0,
                            "tileIndex": 0,
                            "tileType": 0,
                            "special": "normal",
                            "special_delta": 0,
                        },
                        "cardDecisionTimeMs": 1500,
                        "offeredNumbers": [3, 4],
                        "chosenNumber": 4,
                        "numberDecisionTimeMs": 700,
                        "specialTileTriggers": [],
                    },
                    {
                        "runId": "",
                        "turnIndex": 1,
                        "timestampPlayedUnixMs": 1762776002500,
                        "chosenCard": {
                            "type": "Bug",
                            "data": "[CardData: tileType=, ifSign=, ifValue=, thenValue=, elseValue=]",
                        },
                        "wasCorrect": False,
                        "offeredCards": [
                            {
                                "type": "Bug",
                                "data": "[CardData: tileType=, ifSign=, ifValue=, thenValue=, elseValue=]",
                            },
                            {
                                "type": "AllBack2",
                                "data": "[CardData: tileType=, ifSign=, ifValue=, thenValue=, elseValue=]",
                            },
                        ],
                        "playerPositionBefore": {
                            "placeRelativeToBots": 1,
                            "tileMapIndex": 1,
                        },
                        "playerPositionAfter": {
                            "placeRelativeToBots": 1,
                            "tileMapIndex": 2,
                        },
                        "botPositionsBefore": [],
                        "botPositionsAfter": [],
                        "tileBefore": {
                            "tileMapIndex": 1,
                            "tileIndex": 1,
                            "tileType": 1,
                            "special": "normal",
                            "special_delta": 0,
                        },
                        "cardDecisionTimeMs": 2000,
                        "offeredNumbers": [],
                        "chosenNumber": -1,
                        "numberDecisionTimeMs": -1,
                        "specialTileTriggers": [
                            {
                                "chainIndex": 0,
                                "specialTile": {
                                    "tileMapIndex": 2,
                                    "tileIndex": 5,
                                    "tileType": 5,
                                    "special": "skateboard",
                                    "special_delta": 5,
                                },
                                "positionOnSpecialTile": {
                                    "placeRelativeToBots": 1,
                                    "tileMapIndex": 2,
                                },
                                "effectDeltaTiles": 5,
                                "positionAfterEffect": {
                                    "placeRelativeToBots": 1,
                                    "tileMapIndex": 7,
                                },
                            }
                        ],
                    },
                ],
            },
        }

    def _open_recording_window(self):
        return {
            "is_open": True,
            "week_start": date(2026, 3, 9),
            "week_end": date(2026, 3, 15),
            "close_at": datetime(2026, 3, 13, 20, 0, tzinfo=dt_timezone.utc),
            "run_finished_at": datetime(2026, 3, 12, 10, 0, tzinfo=dt_timezone.utc),
        }

    def _closed_recording_window(self):
        return {
            "is_open": False,
            "week_start": date(2026, 3, 2),
            "week_end": date(2026, 3, 8),
            "close_at": datetime(2026, 3, 6, 20, 0, tzinfo=dt_timezone.utc),
            "run_finished_at": datetime(2026, 3, 4, 10, 0, tzinfo=dt_timezone.utc),
        }

    def test_run_ingestion_serializer_accepts_unity_payload(self):
        payload = self._unity_payload()

        serializer = RunIngestionSerializer(data=payload)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        validated = serializer.validated_data
        self.assertEqual(validated["student_id"], self.student.id)
        self.assertTrue(validated["player_won"])
        self.assertEqual(validated["place"], 1)
        self.assertEqual(validated["elapsed_ms"], 45000)
        self.assertEqual(validated["game_map"], payload["run"]["gameMap"]["mapTiles"])
        self.assertEqual(validated["turn_events"][0]["chosen_number"], 4)
        self.assertIsNone(validated["turn_events"][1]["chosen_number"])
        self.assertIsNone(validated["turn_events"][1]["number_decision_time_ms"])

        second_serializer = RunIngestionSerializer(data=self._unity_payload())
        self.assertTrue(second_serializer.is_valid(), second_serializer.errors)
        self.assertEqual(
            validated["run_id"], second_serializer.validated_data["run_id"]
        )

    @mock.patch(
        "digitmileapi.views.get_recording_window_status_for_run_finish",
    )
    def test_runs_ingest_accepts_unity_payload_and_persists_parity_fields(
        self,
        recording_window_mock,
    ):
        recording_window_mock.return_value = self._open_recording_window()

        response = self.client.post(
            "/panel/api/runs/ingest/",
            self._unity_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        run = Run.objects.get(id=response.data["run_id"])
        self.assertEqual(run.student, self.student)
        self.assertEqual(run.place, 1)
        self.assertTrue(run.player_won)
        self.assertEqual(run.elapsed_ms, 45000)
        self.assertEqual(
            run.game_map, self._unity_payload()["run"]["gameMap"]["mapTiles"]
        )
        self.assertEqual(TurnEvent.objects.filter(run=run).count(), 2)
        self.assertEqual(SpecialTileTrigger.objects.filter(turn__run=run).count(), 1)

        first_turn = TurnEvent.objects.get(run=run, turn_index=0)
        second_turn = TurnEvent.objects.get(run=run, turn_index=1)
        self.assertEqual(first_turn.chosen_card_type, "MoveX")
        self.assertEqual(first_turn.chosen_card_family, "move")
        self.assertEqual(
            first_turn.chosen_card["data"],
            "[CardData: tileType=, ifSign=, ifValue=, thenValue=1, elseValue=]",
        )
        self.assertEqual(second_turn.chosen_card_type, "Back")
        self.assertEqual(second_turn.chosen_card_family, "back")
        self.assertIsNone(second_turn.chosen_number)
        self.assertIsNone(second_turn.number_decision_time_ms)

    @mock.patch(
        "digitmileapi.views.get_recording_window_status_for_run_finish",
    )
    def test_runs_ingest_is_idempotent_for_unity_retries(self, recording_window_mock):
        recording_window_mock.return_value = self._open_recording_window()
        payload = self._unity_payload()

        first_response = self.client.post(
            "/panel/api/runs/ingest/",
            payload,
            format="json",
        )
        second_response = self.client.post(
            "/panel/api/runs/ingest/",
            payload,
            format="json",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(Run.objects.count(), 1)
        self.assertEqual(
            first_response.data["run_id"],
            second_response.data["run_id"],
        )

    @mock.patch(
        "digitmileapi.views.get_recording_window_status_for_run_finish",
    )
    def test_runs_ingest_handles_duplicate_key_race_condition(
        self,
        recording_window_mock,
    ):
        recording_window_mock.return_value = self._open_recording_window()

        with mock.patch(
            "digitmileapi.views.Run.objects.create",
            side_effect=IntegrityError(
                'duplicate key value violates unique constraint "digitmileapi_run_pkey"'
            ),
        ):
            response = self.client.post(
                "/panel/api/runs/ingest/",
                self._unity_payload(),
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Run.objects.count(), 0)

    @mock.patch(
        "digitmileapi.views.get_recording_window_status_for_run_finish",
    )
    def test_runs_ingest_matches_insert_run_data_persistence_for_key_fields(
        self,
        recording_window_mock,
    ):
        recording_window_mock.return_value = self._open_recording_window()
        payload = self._unity_payload()

        legacy_response = self.client.post(
            "/panel/api/insertRunData/",
            payload,
            format="json",
        )
        canonical_response = self.client.post(
            "/panel/api/runs/ingest/",
            payload,
            format="json",
        )

        self.assertEqual(legacy_response.status_code, 201)
        self.assertEqual(canonical_response.status_code, 201)

        legacy_run = Run.objects.get(id=legacy_response.data["run_id"])
        canonical_run = Run.objects.get(id=canonical_response.data["run_id"])
        self.assertEqual(legacy_run.level, canonical_run.level)
        self.assertEqual(legacy_run.score, canonical_run.score)
        self.assertEqual(legacy_run.place, canonical_run.place)
        self.assertEqual(legacy_run.player_won, canonical_run.player_won)
        self.assertEqual(legacy_run.elapsed_ms, canonical_run.elapsed_ms)
        self.assertEqual(legacy_run.correct_moves, canonical_run.correct_moves)
        self.assertEqual(legacy_run.wrong_moves, canonical_run.wrong_moves)
        self.assertEqual(legacy_run.game_map, canonical_run.game_map)

        legacy_turns = list(
            TurnEvent.objects.filter(run=legacy_run).order_by("turn_index")
        )
        canonical_turns = list(
            TurnEvent.objects.filter(run=canonical_run).order_by("turn_index")
        )
        self.assertEqual(len(legacy_turns), len(canonical_turns))

        for legacy_turn, canonical_turn in zip(legacy_turns, canonical_turns):
            self.assertEqual(legacy_turn.turn_index, canonical_turn.turn_index)
            self.assertEqual(legacy_turn.chosen_card, canonical_turn.chosen_card)
            self.assertEqual(
                legacy_turn.chosen_card_type, canonical_turn.chosen_card_type
            )
            self.assertEqual(
                legacy_turn.chosen_card_family,
                canonical_turn.chosen_card_family,
            )
            self.assertEqual(legacy_turn.offered_cards, canonical_turn.offered_cards)
            self.assertEqual(legacy_turn.was_correct, canonical_turn.was_correct)
            self.assertEqual(
                legacy_turn.tile_before_index, canonical_turn.tile_before_index
            )
            self.assertEqual(
                legacy_turn.tile_before_type, canonical_turn.tile_before_type
            )
            self.assertEqual(
                legacy_turn.tile_after_index, canonical_turn.tile_after_index
            )
            self.assertEqual(legacy_turn.place_before, canonical_turn.place_before)
            self.assertEqual(legacy_turn.place_after, canonical_turn.place_after)
            self.assertEqual(
                legacy_turn.card_decision_time_ms,
                canonical_turn.card_decision_time_ms,
            )
            self.assertEqual(legacy_turn.chosen_number, canonical_turn.chosen_number)
            self.assertEqual(
                legacy_turn.number_decision_time_ms,
                canonical_turn.number_decision_time_ms,
            )

        legacy_triggers = list(
            SpecialTileTrigger.objects.filter(turn__run=legacy_run).order_by(
                "turn__turn_index",
                "chain_index",
            )
        )
        canonical_triggers = list(
            SpecialTileTrigger.objects.filter(turn__run=canonical_run).order_by(
                "turn__turn_index",
                "chain_index",
            )
        )
        self.assertEqual(len(legacy_triggers), len(canonical_triggers))

        for legacy_trigger, canonical_trigger in zip(
            legacy_triggers, canonical_triggers
        ):
            self.assertEqual(legacy_trigger.chain_index, canonical_trigger.chain_index)
            self.assertEqual(
                legacy_trigger.special_tile_index,
                canonical_trigger.special_tile_index,
            )
            self.assertEqual(
                legacy_trigger.special_tile_type,
                canonical_trigger.special_tile_type,
            )
            self.assertEqual(
                legacy_trigger.effect_delta_tiles,
                canonical_trigger.effect_delta_tiles,
            )
            self.assertEqual(
                legacy_trigger.target_tile_index,
                canonical_trigger.target_tile_index,
            )
            self.assertEqual(
                legacy_trigger.target_tile_type,
                canonical_trigger.target_tile_type,
            )
            self.assertEqual(
                legacy_trigger.place_before, canonical_trigger.place_before
            )
            self.assertEqual(legacy_trigger.place_after, canonical_trigger.place_after)

    @override_settings(BENCHMARK_TIME_OVERRIDE_ENABLED=True)
    def test_runs_ingest_accepts_synthetic_open_week_benchmark_time(self):
        started_at = datetime(2026, 3, 11, 9, 0, tzinfo=dt_timezone.utc)
        finished_at = datetime(2026, 3, 11, 9, 0, 45, tzinfo=dt_timezone.utc)
        payload = self._unity_payload()
        payload["run"]["runStartedUnixMs"] = int(started_at.timestamp() * 1000)
        payload["run"]["runEndedUnixMs"] = int(finished_at.timestamp() * 1000)

        response = self.client.post(
            "/panel/api/runs/ingest/",
            payload,
            format="json",
            HTTP_X_BENCHMARK_REFERENCE_TIME="2026-03-13T19:59:00Z",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Run.objects.count(), 1)

    @override_settings(BENCHMARK_TIME_OVERRIDE_ENABLED=True)
    def test_runs_ingest_rejects_synthetic_closed_week_benchmark_time(self):
        started_at = datetime(2026, 3, 11, 9, 0, tzinfo=dt_timezone.utc)
        finished_at = datetime(2026, 3, 11, 9, 0, 45, tzinfo=dt_timezone.utc)
        payload = self._unity_payload()
        payload["run"]["runStartedUnixMs"] = int(started_at.timestamp() * 1000)
        payload["run"]["runEndedUnixMs"] = int(finished_at.timestamp() * 1000)

        response = self.client.post(
            "/panel/api/runs/ingest/",
            payload,
            format="json",
            HTTP_X_BENCHMARK_REFERENCE_TIME="2026-03-13T20:00:00Z",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(Run.objects.count(), 0)

    @override_settings(BENCHMARK_TIME_OVERRIDE_ENABLED=False)
    @mock.patch(
        "digitmileapi.views.get_recording_window_status_for_run_finish",
    )
    def test_runs_ingest_ignores_benchmark_header_when_override_disabled(
        self,
        recording_window_mock,
    ):
        recording_window_mock.return_value = self._open_recording_window()

        response = self.client.post(
            "/panel/api/runs/ingest/",
            self._unity_payload(),
            format="json",
            HTTP_X_BENCHMARK_REFERENCE_TIME="2026-03-13T20:00:00Z",
        )

        self.assertEqual(response.status_code, 201)
        _, kwargs = recording_window_mock.call_args
        self.assertIsNone(kwargs.get("reference_time"))

    @override_settings(BENCHMARK_TIME_OVERRIDE_ENABLED=True)
    def test_runs_ingest_rejects_invalid_benchmark_reference_time(self):
        response = self.client.post(
            "/panel/api/runs/ingest/",
            self._unity_payload(),
            format="json",
            HTTP_X_BENCHMARK_REFERENCE_TIME="not-a-datetime",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Run.objects.count(), 0)


class RecordingWindowPolicyTests(TestCase):
    def test_recording_window_is_open_before_cutoff(self):
        finished_at = datetime(2026, 3, 11, 14, 0, tzinfo=dt_timezone.utc)
        reference_time = datetime(2026, 3, 13, 19, 59, tzinfo=dt_timezone.utc)

        status = get_recording_window_status_for_run_finish(
            finished_at,
            reference_time=reference_time,
        )

        self.assertTrue(status["is_open"])
        self.assertEqual(status["week_start"], date(2026, 3, 9))
        self.assertEqual(
            status["close_at"],
            datetime(2026, 3, 13, 20, 0, tzinfo=dt_timezone.utc),
        )

    def test_recording_window_closes_at_cutoff_boundary(self):
        finished_at = datetime(2026, 3, 11, 14, 0, tzinfo=dt_timezone.utc)
        reference_time = datetime(2026, 3, 13, 20, 0, tzinfo=dt_timezone.utc)

        status = get_recording_window_status_for_run_finish(
            finished_at,
            reference_time=reference_time,
        )

        self.assertFalse(status["is_open"])

    @mock.patch(
        "digitmileapi.views.get_recording_window_status_for_run_finish",
    )
    def test_runs_ingest_rejects_closed_week_without_partial_write(
        self,
        recording_window_mock,
    ):
        school = School.objects.create(
            name="Closed Week School",
            municipality="Bitola",
            region="Pelagonia",
            address="Closed Week Address 1",
            director_name="Closed Week Director",
            school_email="closed-week-school@example.com",
        )
        teacher = Teacher.objects.create(
            full_name="Teacher Closed Week",
            email="closed-week-teacher@example.com",
            status="APPROVED",
        )
        classroom = Classroom.objects.create(
            classroom_key="CLOSED-1234",
            classroom_name="4-B",
            grade=4,
            teacher=teacher,
            school=school,
        )
        student = Student.objects.create(
            full_name="Student Closed Week",
            grade=4,
            classroom=classroom,
        )
        client = APIClient()
        recording_window_mock.return_value = {
            "is_open": False,
            "week_start": date(2026, 3, 2),
            "week_end": date(2026, 3, 8),
            "close_at": datetime(2026, 3, 6, 20, 0, tzinfo=dt_timezone.utc),
            "run_finished_at": datetime(2026, 3, 4, 10, 0, tzinfo=dt_timezone.utc),
        }

        self.classroom = classroom
        self.student = student
        payload = RunIngestionTests._unity_payload(self)
        payload["classroomKey"] = classroom.classroom_key
        payload["user"] = student.full_name
        payload["userID"] = student.id

        response = client.post(
            "/panel/api/runs/ingest/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(Run.objects.count(), 0)
        self.assertEqual(TurnEvent.objects.count(), 0)
        self.assertEqual(SpecialTileTrigger.objects.count(), 0)


class ReplayArchiveTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name="Test School",
            municipality="Skopje",
            region="Skopje",
            address="Test Address 1",
            director_name="Director Name",
            school_email="school@example.com",
        )
        self.teacher = Teacher.objects.create(
            full_name="Teacher Example",
            email="teacher@example.com",
            status="APPROVED",
        )
        self.classroom = Classroom.objects.create(
            classroom_key="ABC-1234",
            classroom_name="4-A",
            grade=4,
            teacher=self.teacher,
            school=self.school,
        )
        self.student = Student.objects.create(
            full_name="Student Example",
            grade=4,
            classroom=self.classroom,
        )
        self.run = Run.objects.create(
            student=self.student,
            level=4,
            player_won=True,
            score=120,
            place=1,
            elapsed_ms=45000,
            correct_moves=3,
            wrong_moves=1,
            game_map=[{"tileMapIndex": 0, "tileType": 0}],
        )
        self.turn = TurnEvent.objects.create(
            run=self.run,
            turn_index=0,
            timestamp_played=timezone.now(),
            chosen_card={"type": "MoveX", "data": "[CardData: thenValue=2]"},
            chosen_card_type="MoveX",
            chosen_card_family="move",
            chosen_card_tile_type=None,
            offered_cards=[{"type": "MoveX", "data": "[CardData: thenValue=2]"}],
            was_correct=True,
            tile_before_index=0,
            tile_before_type=0,
            tile_after_index=2,
            place_before=1,
            place_after=1,
            bot_positions_before=[],
            bot_positions_after=[],
            card_decision_time_ms=2000,
            offered_numbers=[],
            chosen_number=None,
            number_decision_time_ms=None,
        )
        SpecialTileTrigger.objects.create(
            turn=self.turn,
            chain_index=0,
            special_tile_index=2,
            special_tile_type=5,
            effect_delta_tiles=5,
            target_tile_index=7,
            target_tile_type=0,
            place_before=1,
            place_after=1,
        )

    def test_write_and_verify_archive(self):
        with TemporaryDirectory() as archive_root:
            with override_settings(REPLAY_ARCHIVE_ROOT=archive_root):
                archive = write_replay_archive(self.run)

                self.assertEqual(
                    archive.archive_status, ReplayArchive.ArchiveStatus.READY
                )


class WeeklyAggregationTests(ReplayArchiveTests):
    def setUp(self):
        super().setUp()
        self.turn.chosen_card = {
            "type": "IfXMoveYElseMoveZ",
            "data": "[CardData: tileType=1, ifSign=, ifValue=, thenValue=2, elseValue=1]",
        }
        self.turn.chosen_card_type = "IfXMoveYElseMoveZ"
        self.turn.chosen_card_family = "conditional_tile"
        self.turn.chosen_card_tile_type = 1
        self.turn.offered_cards = [
            {"type": "MoveX", "data": "[CardData: thenValue=2]"},
            {
                "type": "IfXMoveYElseMoveZ",
                "data": "[CardData: tileType=1, ifSign=, ifValue=, thenValue=2, elseValue=1]",
            },
        ]
        self.turn.tile_before_type = 0
        self.turn.number_decision_time_ms = 1500
        self.turn.chosen_number = 4
        self.turn.save()

    def test_aggregate_weekly_rollups_creates_summary_rows(self):
        result = aggregate_weekly_rollups(self.run.created_at.date())

        self.assertEqual(result["run_count"], 1)
        self.assertEqual(StudentWeekStats.objects.count(), 1)
        self.assertEqual(StudentWeekLevelStats.objects.count(), 1)
        self.assertEqual(StudentWeekHotspotStats.objects.count(), 0)
        self.assertEqual(StudentWeekSpecialTileStats.objects.count(), 1)
        self.assertEqual(StudentWeekCardTypeStats.objects.count(), 1)
        self.assertEqual(StudentWeekNumberChoiceStats.objects.count(), 1)
        self.assertEqual(ClassroomWeekStats.objects.count(), 1)

        week_stats = StudentWeekStats.objects.get(student=self.student)
        self.assertEqual(week_stats.runs, 1)
        self.assertEqual(week_stats.wins, 1)
        self.assertEqual(week_stats.correct_moves, 3)
        self.assertEqual(week_stats.wrong_moves, 1)

        family_stats = StudentWeekCardFamilyStats.objects.get(
            student=self.student,
            card_family="conditional_tile",
        )
        self.assertEqual(family_stats.card_family, "conditional_tile")
        self.assertEqual(family_stats.offered_count, 1)
        self.assertEqual(family_stats.chosen_count, 1)

        conditional_stats = StudentWeekConditionalStats.objects.get(
            student=self.student
        )
        self.assertEqual(conditional_stats.conditional_kind, "tile")
        self.assertEqual(conditional_stats.total_count, 1)
        self.assertEqual(conditional_stats.else_count, 1)

    def test_aggregate_weekly_rollups_creates_card_type_rollups_with_clipping(self):
        self.turn.card_decision_time_ms = 130000
        self.turn.save(update_fields=["card_decision_time_ms"])

        aggregate_weekly_rollups(self.run.created_at.date())

        conditional_stats = StudentWeekCardTypeStats.objects.get(
            student=self.student,
            card_type="IfXMoveYElseMoveZ",
        )

        clipped_value, was_clipped = clip_decision_time_ms(130000)
        self.assertTrue(was_clipped)
        self.assertEqual(conditional_stats.chosen_count, 1)
        self.assertEqual(conditional_stats.decision_time_sum_ms, 130000)
        self.assertEqual(conditional_stats.clipped_decision_time_sum_ms, clipped_value)
        self.assertEqual(conditional_stats.outlier_count, 1)

    def test_bag_conditional_rollups_follow_turn_order_for_else_count(self):
        self.turn.chosen_card = {
            "type": "IfBagEqualXMoveYElseMoveZ",
            "data": "[CardData: tileType=, ifSign===, ifValue=2, thenValue=3, elseValue=1]",
        }
        self.turn.chosen_card_type = "IfBagEqualXMoveYElseMoveZ"
        self.turn.chosen_card_family = "conditional_bag_eq"
        self.turn.chosen_card_tile_type = None
        self.turn.chosen_number = 4
        self.turn.number_decision_time_ms = 900
        self.turn.save(
            update_fields=[
                "chosen_card",
                "chosen_card_type",
                "chosen_card_family",
                "chosen_card_tile_type",
                "chosen_number",
                "number_decision_time_ms",
            ]
        )

        TurnEvent.objects.create(
            run=self.run,
            turn_index=1,
            timestamp_played=timezone.now(),
            chosen_card={
                "type": "IfBagGreaterXMoveYElseMoveZ",
                "data": "[CardData: tileType=, ifSign=>, ifValue=3, thenValue=2, elseValue=1]",
            },
            chosen_card_type="IfBagGreaterXMoveYElseMoveZ",
            chosen_card_family="conditional_bag_gt",
            chosen_card_tile_type=None,
            offered_cards=[
                {
                    "type": "IfBagGreaterXMoveYElseMoveZ",
                    "data": "[CardData: tileType=, ifSign=>, ifValue=3, thenValue=2, elseValue=1]",
                }
            ],
            was_correct=True,
            tile_before_index=2,
            tile_before_type=1,
            tile_after_index=4,
            place_before=1,
            place_after=1,
            bot_positions_before=[],
            bot_positions_after=[],
            card_decision_time_ms=1400,
            offered_numbers=[1, 3, 5],
            chosen_number=1,
            number_decision_time_ms=700,
        )

        aggregate_weekly_rollups(self.run.created_at.date())

        eq_stats = StudentWeekConditionalStats.objects.get(
            student=self.student,
            conditional_kind=StudentWeekConditionalStats.ConditionalKind.BAG,
            bucket_key="eq",
        )
        gt_stats = StudentWeekConditionalStats.objects.get(
            student=self.student,
            conditional_kind=StudentWeekConditionalStats.ConditionalKind.BAG,
            bucket_key="gt",
        )

        self.assertEqual(eq_stats.total_count, 1)
        self.assertEqual(eq_stats.else_count, 1)
        self.assertEqual(gt_stats.total_count, 1)
        self.assertEqual(gt_stats.else_count, 0)

        call_command(
            "verify_weekly_rollups",
            self.run.created_at.date().isoformat(),
        )

    def test_rollup_analytics_reads_compacted_history(self):
        aggregate_weekly_rollups(self.run.created_at.date())
        self.run.raw_data_compacted_at = timezone.now()
        self.run.save(update_fields=["raw_data_compacted_at", "updated_at"])
        TurnEvent.objects.filter(run=self.run).delete()
        SpecialTileTrigger.objects.filter(turn__run=self.run).delete()

        share = offer_choice_share_by_family(student_ids=[self.student.id])
        self.assertEqual(len(share), 2)
        self.assertEqual(
            next(row for row in share if row["family"] == "conditional_tile")["chosen"],
            1,
        )

        accuracy = card_accuracy_by_family_by_level(student_ids=[self.student.id])
        self.assertEqual(len(accuracy), 2)
        self.assertEqual(
            next(row for row in accuracy if row["family"] == "conditional_tile")[
                "accuracy"
            ],
            100,
        )

        tile_accuracy = tile_conditional_accuracy_by_tile_type_by_level(
            student_ids=[self.student.id]
        )
        self.assertEqual(tile_accuracy["by_tile_type"][0]["tile_type"], 1)
        self.assertEqual(tile_accuracy["by_tile_type"][0]["else_rate"], 100)

        number_distribution = number_choice_distribution_by_level(
            student_ids=[self.student.id]
        )
        self.assertEqual(number_distribution[0]["chosen_number"], 4)

        self.assertEqual(
            bag_conditional_accuracy_by_comparator_by_level(
                student_ids=[self.student.id]
            ),
            {"by_comparator": [], "else_rate_by_level": []},
        )

    def test_decision_time_by_card_type_merges_rollups_and_hot_rows(self):
        self.turn.card_decision_time_ms = 130000
        self.turn.save(update_fields=["card_decision_time_ms"])
        aggregate_weekly_rollups(self.run.created_at.date())
        self.run.raw_data_compacted_at = timezone.now()
        self.run.save(update_fields=["raw_data_compacted_at", "updated_at"])
        TurnEvent.objects.filter(run=self.run).delete()
        SpecialTileTrigger.objects.filter(turn__run=self.run).delete()

        hot_run = Run.objects.create(
            student=self.student,
            level=4,
            player_won=False,
            score=90,
            place=2,
            elapsed_ms=30000,
            correct_moves=1,
            wrong_moves=0,
            game_map=[{"tileMapIndex": 0, "tileType": 0}],
        )
        TurnEvent.objects.create(
            run=hot_run,
            turn_index=0,
            timestamp_played=timezone.now(),
            chosen_card={
                "type": "IfXMoveYElseMoveZ",
                "data": "[CardData: tileType=1, ifSign=, ifValue=, thenValue=3, elseValue=1]",
            },
            chosen_card_type="IfXMoveYElseMoveZ",
            chosen_card_family="conditional_tile",
            chosen_card_tile_type=None,
            offered_cards=[
                {
                    "type": "IfXMoveYElseMoveZ",
                    "data": "[CardData: tileType=1, ifSign=, ifValue=, thenValue=3, elseValue=1]",
                }
            ],
            was_correct=True,
            tile_before_index=0,
            tile_before_type=0,
            tile_after_index=3,
            place_before=2,
            place_after=2,
            bot_positions_before=[],
            bot_positions_after=[],
            card_decision_time_ms=800,
            offered_numbers=[],
            chosen_number=None,
            number_decision_time_ms=None,
        )

        payload = decision_time_by_card_type(student_ids=[self.student.id])

        self.assertIn("summary_by_card_type", payload)
        self.assertIn("weekly_series_by_card_type", payload)
        conditional_summary = payload["summary_by_card_type"]["IfXMoveYElseMoveZ"]
        self.assertEqual(conditional_summary["count"], 2)
        self.assertEqual(conditional_summary["raw_avg"], (130000 + 800) / 2)
        self.assertEqual(conditional_summary["avg"], (120000 + 800) / 2)
        self.assertEqual(conditional_summary["outlier_count"], 1)
        self.assertTrue(payload["weekly_series_by_card_type"]["IfXMoveYElseMoveZ"])

    def test_rebuild_and_verify_weekly_rollups_commands(self):
        call_command(
            "rebuild_weekly_rollups",
            self.run.created_at.date().isoformat(),
            "--update-compaction",
            "--rebuild-run-buckets",
        )

        self.assertEqual(
            StudentWeekStats.objects.filter(student=self.student).count(), 1
        )
        self.assertEqual(
            WeeklyCompactionRun.objects.filter(
                week_start=week_start_for(self.run.created_at.date()),
                status=WeeklyCompactionRun.Status.AGGREGATED,
            ).count(),
            1,
        )

        call_command(
            "verify_weekly_rollups",
            self.run.created_at.date().isoformat(),
            "--verify-run-buckets",
        )

    def test_compact_weekly_runs_archives_and_deletes_hot_rows(self):
        with TemporaryDirectory() as archive_root:
            with override_settings(REPLAY_ARCHIVE_ROOT=archive_root):
                call_command(
                    "compact_weekly_runs",
                    self.run.created_at.date().isoformat(),
                )

                self.run.refresh_from_db()
                self.assertIsNotNone(self.run.raw_data_compacted_at)
                self.assertEqual(TurnEvent.objects.filter(run=self.run).count(), 0)
                self.assertEqual(
                    SpecialTileTrigger.objects.filter(turn__run=self.run).count(), 0
                )
                self.assertEqual(ReplayArchive.objects.filter(run=self.run).count(), 1)
                self.assertEqual(
                    StudentWeekStats.objects.filter(student=self.student).count(), 1
                )
                self.assertEqual(
                    WeeklyCompactionRun.objects.filter(
                        week_start=week_start_for(self.run.created_at.date()),
                        status=WeeklyCompactionRun.Status.COMPACTED,
                    ).count(),
                    1,
                )

                replay_payload = get_replay_payload_for_run(self.run)
                self.assertEqual(replay_payload["run_id"], self.run.id)
                self.assertEqual(len(replay_payload["turns"]), 1)
                archive = ReplayArchive.objects.get(run=self.run)
                self.assertTrue(archive.storage_path.endswith(f"{self.run.id}.json.gz"))

                payload = load_archive_payload(archive)
                self.assertEqual(payload["run"]["run_id"], self.run.id)
                self.assertEqual(payload["run"]["student_name"], self.student.full_name)
                self.assertEqual(len(payload["turns"]), 1)
                self.assertEqual(
                    payload["turns"][0]["special_triggers"][0]["special_tile_type"], 5
                )

                self.assertTrue(verify_replay_archive(archive))

    def test_archived_run_uses_archive_payload(self):
        with TemporaryDirectory() as archive_root:
            with override_settings(REPLAY_ARCHIVE_ROOT=archive_root):
                archive = write_replay_archive(self.run)
                self.run.raw_data_compacted_at = timezone.now()
                self.run.save(update_fields=["raw_data_compacted_at", "updated_at"])

                payload = get_replay_payload_for_run(self.run)

                self.assertEqual(payload["run_id"], self.run.id)
                self.assertEqual(payload["student"], self.student.full_name)
                self.assertEqual(
                    payload["turns"][0]["special_triggers"][0]["special_tile_index"], 2
                )
                self.assertEqual(
                    archive.archive_status, ReplayArchive.ArchiveStatus.READY
                )


class RunBucketTrendTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name="Trend School",
            municipality="Skopje",
            region="Skopje",
            address="Trend Address 1",
            director_name="Trend Director",
            school_email="trend-school@example.com",
        )
        self.teacher = Teacher.objects.create(
            full_name="Teacher Trend",
            email="trend-teacher@example.com",
            status="APPROVED",
        )
        self.classroom = Classroom.objects.create(
            classroom_key="TREND-1234",
            classroom_name="6-A",
            grade=6,
            teacher=self.teacher,
            school=self.school,
        )
        self.student = Student.objects.create(
            full_name="Student Trend",
            grade=6,
            classroom=self.classroom,
        )

    def _create_run(self, *, level, created_at, correct_moves, wrong_moves, score):
        run = Run.objects.create(
            student=self.student,
            level=level,
            player_won=correct_moves >= wrong_moves,
            score=score,
            place=1 if correct_moves >= wrong_moves else 2,
            elapsed_ms=30000 + score,
            correct_moves=correct_moves,
            wrong_moves=wrong_moves,
            game_map=[{"tileMapIndex": 0, "tileType": 0}],
        )
        Run.objects.filter(id=run.id).update(
            created_at=created_at, updated_at=created_at
        )
        run.refresh_from_db()
        return run

    def test_run_bucket_assignment_is_deterministic(self):
        base_time = datetime(2026, 1, 5, 9, 0, tzinfo=dt_timezone.utc)
        runs = [
            self._create_run(
                level=2,
                created_at=base_time + timedelta(minutes=index),
                correct_moves=3,
                wrong_moves=1,
                score=100 + index,
            )
            for index in range(7)
        ]

        result = rebuild_run_bucket_trends(
            Run.objects.filter(id__in=[run.id for run in runs])
        )

        self.assertEqual(result["bucket_rows"], 2)
        buckets = list(
            StudentRunBucketTrend.objects.filter(
                student=self.student, level=2
            ).order_by("bucket_index")
        )
        self.assertEqual(len(buckets), 2)
        self.assertEqual(buckets[0].bucket_index, 0)
        self.assertEqual(buckets[0].run_count, 5)
        self.assertEqual(buckets[0].first_run_created_at, runs[0].created_at)
        self.assertEqual(buckets[0].last_run_created_at, runs[4].created_at)
        self.assertEqual(buckets[1].bucket_index, 1)
        self.assertEqual(buckets[1].run_count, 2)
        self.assertEqual(buckets[1].first_run_created_at, runs[5].created_at)
        self.assertEqual(buckets[1].last_run_created_at, runs[6].created_at)

    def test_run_bucket_points_merge_compacted_history_with_hot_tail(self):
        base_time = datetime(2026, 1, 5, 9, 0, tzinfo=dt_timezone.utc)
        compacted_runs = [
            self._create_run(
                level=3,
                created_at=base_time + timedelta(minutes=index),
                correct_moves=4,
                wrong_moves=1,
                score=120 + index,
            )
            for index in range(5)
        ]
        rebuild_run_bucket_trends(
            Run.objects.filter(id__in=[run.id for run in compacted_runs])
        )
        Run.objects.filter(id__in=[run.id for run in compacted_runs]).update(
            raw_data_compacted_at=timezone.now()
        )

        hot_runs = [
            self._create_run(
                level=3,
                created_at=base_time + timedelta(minutes=10 + index),
                correct_moves=2 + index,
                wrong_moves=1,
                score=150 + index,
            )
            for index in range(2)
        ]

        payload = get_student_run_bucket_points(self.student, level=3)

        self.assertEqual(len(payload["by_level"][3]), 2)
        self.assertEqual(payload["by_level"][3][0]["run_count"], 5)
        self.assertEqual(payload["by_level"][3][1]["run_count"], 2)
        self.assertEqual(payload["by_level"][3][1]["bucket_index"], 1)
        self.assertEqual(
            payload["by_level"][3][1]["first_run_created_at"],
            hot_runs[0].created_at,
        )

    def test_student_dashboard_info_uses_bucket_learning_curves(self):
        base_time = datetime(2026, 1, 6, 8, 0, tzinfo=dt_timezone.utc)
        accuracy_profiles = [
            (1, 4),
            (1, 4),
            (1, 4),
            (1, 4),
            (1, 4),
            (3, 2),
            (3, 2),
            (3, 2),
            (3, 2),
            (3, 2),
            (5, 0),
            (5, 0),
            (5, 0),
            (5, 0),
            (5, 0),
        ]
        for index, (correct_moves, wrong_moves) in enumerate(accuracy_profiles):
            self._create_run(
                level=4,
                created_at=base_time + timedelta(minutes=index),
                correct_moves=correct_moves,
                wrong_moves=wrong_moves,
                score=80 + index * 5,
            )

        dashboard_info = _build_student_dashboard_info(self.student)

        self.assertIsNotNone(dashboard_info)
        self.assertEqual(dashboard_info["total_runs"], 15)
        self.assertEqual(len(dashboard_info["accuracy_per_game"]), 3)
        self.assertEqual(dashboard_info["learning_curve_trend"], "improving")
        self.assertGreater(dashboard_info["learning_curve_slope"], 0)
        self.assertEqual(
            dashboard_info["level_performance"][4]["learning_curve_trend"], "improving"
        )


class BenchmarkToolingTests(TestCase):
    def test_prepare_benchmark_dataset_creates_report_and_compacts_old_weeks(self):
        with TemporaryDirectory() as temp_dir:
            report_path = f"{temp_dir}/dataset-report.json"

            call_command(
                "prepare_benchmark_dataset",
                teachers=1,
                classrooms_per_teacher=1,
                students_per_classroom=2,
                weeks=2,
                runs_per_student_per_week=1,
                avg_turns_per_run=3,
                card_mix_profile="balanced",
                bag_level_ratio=0.3,
                hot_weeks=1,
                anchor_week_start="2026-03-09",
                clear=True,
                output=report_path,
            )

            report = json.loads(Path(report_path).read_text(encoding="utf-8"))

            self.assertEqual(report["anchor_week_start"], "2026-03-09")
            self.assertEqual(report["hot_week_start"], "2026-03-09")
            self.assertEqual(report["hot_week_end"], "2026-03-15")
            self.assertEqual(report["synthetic_now"], "2026-03-13T19:00:00+00:00")
            self.assertEqual(
                report["synthetic_week_close_at"],
                "2026-03-13T20:00:00+00:00",
            )
            self.assertEqual(report["counts"]["teachers"], 1)
            self.assertEqual(report["counts"]["classrooms"], 1)
            self.assertEqual(report["counts"]["students"], 2)
            self.assertEqual(report["counts"]["runs"], 4)
            self.assertEqual(len(report["compactions"]), 1)
            self.assertTrue(report["weeks"][0]["compacted"])
            self.assertTrue(report["weeks"][1]["hot"])
            self.assertEqual(report["weeks"][0]["week_start"], "2026-03-02")
            self.assertEqual(report["weeks"][1]["week_start"], "2026-03-09")
            self.assertTrue(report["ingest_targets_hot_week"])
            self.assertTrue(report["teacher_targets"])
            self.assertTrue(report["dashboard_filter_targets"])
            self.assertTrue(report["replay_targets_hot"])

    def test_prepare_benchmark_dataset_normalizes_anchor_week_start(self):
        with TemporaryDirectory() as temp_dir:
            report_path = f"{temp_dir}/dataset-report.json"

            call_command(
                "prepare_benchmark_dataset",
                teachers=1,
                classrooms_per_teacher=1,
                students_per_classroom=1,
                weeks=1,
                runs_per_student_per_week=1,
                avg_turns_per_run=3,
                card_mix_profile="balanced",
                bag_level_ratio=0.3,
                hot_weeks=1,
                anchor_week_start="2026-03-11",
                clear=True,
                output=report_path,
            )

            report = json.loads(Path(report_path).read_text(encoding="utf-8"))

            self.assertEqual(report["anchor_week_start"], "2026-03-09")
            self.assertEqual(report["weeks"][0]["week_start"], "2026-03-09")

    def test_benchmark_teacher_analytics_writes_report(self):
        with TemporaryDirectory() as temp_dir:
            dataset_path = f"{temp_dir}/dataset-report.json"
            benchmark_path = f"{temp_dir}/benchmark-report.json"

            call_command(
                "prepare_benchmark_dataset",
                teachers=1,
                classrooms_per_teacher=1,
                students_per_classroom=2,
                weeks=1,
                runs_per_student_per_week=1,
                avg_turns_per_run=3,
                card_mix_profile="balanced",
                bag_level_ratio=0.3,
                hot_weeks=1,
                anchor_week_start="2026-03-09",
                clear=True,
                output=dataset_path,
            )
            dataset_report = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
            teacher_id = dataset_report["teachers"][0]["teacher_id"]

            call_command(
                "benchmark_teacher_analytics",
                teacher_id,
                iterations=2,
                scenario_name="test_benchmark",
                output=benchmark_path,
            )

            benchmark_report = json.loads(
                Path(benchmark_path).read_text(encoding="utf-8")
            )

            self.assertEqual(benchmark_report["scenario_name"], "test_benchmark")
            self.assertEqual(benchmark_report["teacher_id"], teacher_id)
            self.assertIn("analytics_payload", benchmark_report["measurements_ms"])
            self.assertIn("table_sizes_bytes", benchmark_report)
