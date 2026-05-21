"""
Unit tests for the parallel per-teacher orchestrator in compact_weekly_runs.

These tests exercise the orchestration helpers in isolation by stubbing the
subprocess.Popen call site. They verify:

  - argv constructed for each worker is correct given (week_start, teacher_id,
    options).
  - The orchestrator dispatches one worker per discovered teacher.
  - It respects max_workers as an in-flight cap.
  - It correctly parses the JSON sentinel line out of stdout and aggregates
    slice results in teacher-discovery order.
  - It raises CommandError on a worker non-zero exit or missing sentinel line.

The end-to-end real-subprocess path is covered indirectly by the sequential
per-teacher tests in test_rollup_accuracy.py — those verify the actual
slice work, which is identical whether a worker is invoked in-process or via
subprocess. What this file pins down is the orchestration layer.
"""

import json
from datetime import date
from unittest import TestCase, mock

from django.core.management.base import CommandError

from digitmileapi.management.commands.compact_weekly_runs import (
    Command,
    SLICE_RESULT_SENTINEL,
)


def _make_slice_result(run_count, archives=0, turns_deleted=0):
    return {
        "run_count": run_count,
        "turn_count": run_count * 4,
        "trigger_count": run_count * 2,
        "archive_runs_written": archives,
        "archive_runs_verified": archives,
        "archive_bytes_written": archives * 1024,
        "turn_rows_deleted": turns_deleted,
        "trigger_rows_deleted": turns_deleted // 2,
    }


class FakePopen:
    """Stand-in for subprocess.Popen with controllable stdout/returncode."""

    def __init__(self, stdout, returncode=0, stderr=""):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._polled = False

    def poll(self):
        # Return None once so _wait_one's poll loop runs at least one cycle,
        # then return the exit code. Approximates a real subprocess that
        # takes nonzero wall time to finish.
        if not self._polled:
            self._polled = True
            return None
        return self.returncode

    def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        pass


class SpawnSliceWorkerArgvTest(TestCase):
    """_spawn_slice_worker should build a faithful manage.py argv."""

    def test_argv_includes_required_worker_flags(self):
        command = Command()
        options = {
            "dry_run": False,
            "overwrite_archives": False,
            "clear_game_map": False,
        }
        captured = {}

        def fake_popen(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return FakePopen("")

        with mock.patch(
            "digitmileapi.management.commands.compact_weekly_runs.subprocess.Popen",
            side_effect=fake_popen,
        ):
            command._spawn_slice_worker(date(2025, 9, 8), 42, options)

        argv = captured["argv"]
        self.assertIn("compact_weekly_runs", argv)
        self.assertIn("2025-09-08", argv)
        self.assertIn("--teacher-id", argv)
        self.assertIn("42", argv)
        self.assertIn("--skip-verification", argv)
        self.assertIn("--emit-json-result", argv)
        # Optional flags must NOT be propagated unless set in options.
        self.assertNotIn("--dry-run", argv)
        self.assertNotIn("--overwrite-archives", argv)
        self.assertNotIn("--clear-game-map", argv)

    def test_argv_propagates_optional_flags(self):
        command = Command()
        options = {
            "dry_run": True,
            "overwrite_archives": True,
            "clear_game_map": True,
        }
        captured = {}

        def fake_popen(argv, **kwargs):
            captured["argv"] = argv
            return FakePopen("")

        with mock.patch(
            "digitmileapi.management.commands.compact_weekly_runs.subprocess.Popen",
            side_effect=fake_popen,
        ):
            command._spawn_slice_worker(date(2025, 9, 8), 7, options)

        argv = captured["argv"]
        self.assertIn("--dry-run", argv)
        self.assertIn("--overwrite-archives", argv)
        self.assertIn("--clear-game-map", argv)


class ParseSliceResultTest(TestCase):
    """_parse_slice_result extracts the JSON sentinel line from worker stdout."""

    def test_extracts_sentinel_line(self):
        payload = _make_slice_result(run_count=123, archives=10, turns_deleted=200)
        stdout = (
            "some warmup line\n"
            f"{SLICE_RESULT_SENTINEL} {json.dumps(payload)}\n"
            "Compaction complete (teacher=7): runs=123, ...\n"
        )
        result = Command._parse_slice_result(stdout, teacher_id=7)
        self.assertEqual(result, payload)

    def test_picks_last_sentinel_when_multiple(self):
        # Defensive: a worker should emit exactly one sentinel, but if a
        # downstream log echo duplicated it, the most recent is authoritative.
        first = _make_slice_result(run_count=1)
        last = _make_slice_result(run_count=999)
        stdout = (
            f"{SLICE_RESULT_SENTINEL} {json.dumps(first)}\n"
            f"{SLICE_RESULT_SENTINEL} {json.dumps(last)}\n"
        )
        result = Command._parse_slice_result(stdout, teacher_id=1)
        self.assertEqual(result["run_count"], 999)

    def test_missing_sentinel_raises(self):
        with self.assertRaises(CommandError) as ctx:
            Command._parse_slice_result(
                "Compaction complete (teacher=7): runs=123\n",
                teacher_id=7,
            )
        self.assertIn("did not emit", str(ctx.exception))

    def test_empty_stdout_raises(self):
        with self.assertRaises(CommandError):
            Command._parse_slice_result("", teacher_id=7)

    def test_malformed_json_raises(self):
        stdout = f"{SLICE_RESULT_SENTINEL} {{not valid json"
        with self.assertRaises(CommandError) as ctx:
            Command._parse_slice_result(stdout, teacher_id=7)
        self.assertIn("malformed", str(ctx.exception))


class RunSlicesParallelTest(TestCase):
    """The orchestrator dispatches one worker per teacher, aggregates results."""

    def _stub_spawn(self, slice_results_by_teacher, failures=None):
        """
        Build a fake _spawn_slice_worker that returns a FakePopen producing
        the configured slice result (or non-zero exit) for each teacher_id.
        """
        failures = failures or {}

        def fake_spawn(self_arg, week_start, teacher_id, options):
            if teacher_id in failures:
                stderr = failures[teacher_id]
                return FakePopen("", returncode=1, stderr=stderr)
            payload = slice_results_by_teacher[teacher_id]
            stdout = f"{SLICE_RESULT_SENTINEL} {json.dumps(payload)}\n"
            return FakePopen(stdout, returncode=0)

        return fake_spawn

    def test_one_worker_per_teacher_results_in_discovery_order(self):
        teacher_ids = [10, 20, 30, 40]
        slice_results_by_teacher = {
            10: _make_slice_result(run_count=100, archives=5),
            20: _make_slice_result(run_count=200, archives=6),
            30: _make_slice_result(run_count=300, archives=7),
            40: _make_slice_result(run_count=400, archives=8),
        }
        command = Command()
        # stdout writes during orchestration end up here — harmless.
        command.stdout = mock.MagicMock()

        with mock.patch.object(
            Command,
            "_spawn_slice_worker",
            new=self._stub_spawn(slice_results_by_teacher),
        ):
            results = command._run_slices_parallel(
                teacher_ids,
                week_start=date(2025, 9, 8),
                max_workers=2,
                options={
                    "dry_run": False,
                    "overwrite_archives": False,
                    "clear_game_map": False,
                },
            )

        self.assertEqual(len(results), len(teacher_ids))
        # Order must match discovery order so _finalize_week_record sees
        # deterministic aggregation.
        self.assertEqual(
            [r["run_count"] for r in results], [100, 200, 300, 400]
        )

        # Sum aggregation matches the per-slice sum.
        totals = Command._sum_slice_results(results)
        self.assertEqual(totals["run_count"], 1000)
        self.assertEqual(totals["archive_runs_verified"], 26)

    def test_worker_nonzero_exit_raises_commanderror(self):
        teacher_ids = [10, 20]
        command = Command()
        command.stdout = mock.MagicMock()

        with mock.patch.object(
            Command,
            "_spawn_slice_worker",
            new=self._stub_spawn(
                {10: _make_slice_result(run_count=100)},
                failures={20: "boom: archive verification failed"},
            ),
        ):
            with self.assertRaises(CommandError) as ctx:
                command._run_slices_parallel(
                    teacher_ids,
                    week_start=date(2025, 9, 8),
                    max_workers=2,
                    options={
                        "dry_run": False,
                        "overwrite_archives": False,
                        "clear_game_map": False,
                    },
                )

        self.assertIn("teacher_id=20", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))

    def test_respects_max_workers_in_flight_cap(self):
        """
        With max_workers=2 and 5 teachers, no more than 2 workers should ever
        be alive at once. Instrument FakePopen via a shared counter to verify.
        """
        teacher_ids = [10, 20, 30, 40, 50]
        slice_results_by_teacher = {
            t: _make_slice_result(run_count=t) for t in teacher_ids
        }
        peak = {"in_flight": 0, "current": 0}
        original_communicate = FakePopen.communicate

        def tracked_spawn(self_arg, week_start, teacher_id, options):
            peak["current"] += 1
            peak["in_flight"] = max(peak["in_flight"], peak["current"])
            stdout = (
                f"{SLICE_RESULT_SENTINEL} "
                f"{json.dumps(slice_results_by_teacher[teacher_id])}\n"
            )
            proc = FakePopen(stdout, returncode=0)

            def communicate_and_decrement():
                peak["current"] -= 1
                return original_communicate(proc)

            proc.communicate = communicate_and_decrement
            return proc

        command = Command()
        command.stdout = mock.MagicMock()

        with mock.patch.object(
            Command, "_spawn_slice_worker", new=tracked_spawn
        ):
            command._run_slices_parallel(
                teacher_ids,
                week_start=date(2025, 9, 8),
                max_workers=2,
                options={
                    "dry_run": False,
                    "overwrite_archives": False,
                    "clear_game_map": False,
                },
            )

        self.assertLessEqual(
            peak["in_flight"],
            2,
            f"Saw {peak['in_flight']} workers in flight with max_workers=2",
        )
