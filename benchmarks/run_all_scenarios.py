#!/usr/bin/env python
"""Run the full benchmark set for the thesis evaluation chapter.

For every scenario this script:

  1. Invokes ``python benchmarks/run_scenario.py <scenario.json>`` with the
     right ``BENCHMARK_DISABLE_PGBOUNCER`` value injected into the subprocess
     environment (never exported to the parent shell, so a Ctrl-C never
     leaves the variable lingering).
  2. Locates the produced report under
     ``benchmarks/reports/[no_pgbouncer/]<name>.json``.
  3. Reads ``scenario_summary.stack_state`` and verifies the runtime probe
     matches what the scenario's overlay set was supposed to flip — *not*
     just that docker compose was given the override file. A mismatch aborts
     the suite (or logs a warning under ``--continue-on-fail``).
  4. Moves the report to ``benchmarks/server_reports/<final_name>.json``,
     overwriting any prior copy. The intermediate ``benchmarks/reports/``
     tree is left untouched so reruns are cheap.

Usage (run from the repo root, on the server):

    python benchmarks/run_all_scenarios.py            # full suite
    python benchmarks/run_all_scenarios.py --list     # show plan, no exec
    python benchmarks/run_all_scenarios.py --only endurance_steady,mixed_steady
    python benchmarks/run_all_scenarios.py --from before_all_optimizations
    python benchmarks/run_all_scenarios.py --skip-existing
    python benchmarks/run_all_scenarios.py --continue-on-fail

The suite is declared in ``SUITE`` below. Each entry says which scenario
JSON to load, whether to disable PgBouncer for it, where the final report
should land, and what stack-state values the overlays are expected to
produce. Verification is conservative — if a probe value is unknown for a
scenario (e.g. the baseline image's ``settings.py`` predates the
``DJANGO_CACHE_BACKEND`` env switch), the entry passes ``None`` for that
expected field and the script does not enforce it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_SCENARIO = REPO_ROOT / "benchmarks" / "run_scenario.py"
COMPARE_REPORTS = REPO_ROOT / "benchmarks" / "compare_reports.py"
SCENARIOS_DIR = REPO_ROOT / "benchmarks" / "scenarios"
REPORTS_DIR = REPO_ROOT / "benchmarks" / "reports"
SERVER_REPORTS_DIR = REPO_ROOT / "benchmarks" / "server_reports"


@dataclass
class Expected:
    """What the runtime probe should report for an overlay set to count as applied.

    Any field left as ``None`` is *not* checked. Use ``None`` when the
    baseline image does not honor the env switch (e.g. dummy-cache against a
    pre-D commit) or when the probe field is irrelevant for the scenario.
    """

    pgbouncer_bypassed: Optional[bool] = None       # DB_HOST != benchmark-pgbouncer
    pg_synchronous_commit: Optional[str] = None     # 'on' under pg-defaults, 'off' under B-tuning
    django_cache_backend: Optional[str] = None      # 'dummy.DummyCache' or 'django_redis.cache.RedisCache'
    flusher_running: Optional[bool] = None          # False under no-flusher (busybox swap)


@dataclass
class SuiteEntry:
    scenario: str                # filename stem under benchmarks/scenarios/
    disable_pgbouncer: bool      # exports BENCHMARK_DISABLE_PGBOUNCER=1 for this subprocess
    output_name: str             # final filename (no extension) under server_reports/
    expected: Expected
    purpose: str = ""            # human-readable label printed in --list
    enabled: bool = True         # set False to keep the entry visible but skipped


# -----------------------------------------------------------------------------
# Suite definition — everything needed for the thesis evaluation chapter.
# -----------------------------------------------------------------------------
#
# Naming convention for output_name: each scenario lands under
# ``benchmarks/server_reports/<output_name>.json``. PgBouncer is disabled
# uniformly across the NFR + marginal comparison set, mirroring the
# production decision. The PgBouncer "on vs off" marginal comparison (A) is
# *not* re-run — its evidence already lives in
# ``benchmarks/server_reports/comparison_pgbouncer.md`` and is deferred to
# the future-work / results discussion per the chapter scope.
SUITE: list[SuiteEntry] = [
    # ---- NFR scenarios (current tree, no PgBouncer) -------------------------
    SuiteEntry(
        scenario="endurance_steady",
        disable_pgbouncer=True,
        output_name="endurance_steady",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="off",
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="NFR-1 endurance @ 11 RPS for 15 min",
    ),
    SuiteEntry(
        scenario="lesson_bell_medium",
        disable_pgbouncer=True,
        output_name="lesson_bell_medium",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="off",
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="NFR-2 lesson-bell burst absorption (medium adoption, ~29 RPS peak)",
    ),
    SuiteEntry(
        scenario="lesson_bell_high",
        disable_pgbouncer=True,
        output_name="lesson_bell_high",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="off",
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="NFR-2 lesson-bell burst absorption (high adoption, ~44 RPS peak)",
    ),
    SuiteEntry(
        scenario="mixed_steady",
        disable_pgbouncer=True,
        output_name="mixed_steady",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="off",
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="NFR-3 dashboard latency + NFR-4 compaction (post-traffic)",
    ),
    SuiteEntry(
        scenario="overload_recovery",
        disable_pgbouncer=True,
        output_name="overload_recovery",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="off",
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="NFR-5 overload recovery (4-stage profile)",
    ),

    # ---- Cumulative headline pair ------------------------------------------
    SuiteEntry(
        scenario="before_all_optimizations",
        disable_pgbouncer=False,  # scenario JSON already declares no-pgbouncer.yml
        output_name="before_all_optimizations",
        expected=Expected(
            pgbouncer_bypassed=True,        # via the scenario's own no-pgbouncer.yml
            pg_synchronous_commit="on",     # pg-defaults reverts optimization B
            django_cache_backend=None,      # baseline image predates DJANGO_CACHE_BACKEND switch
            flusher_running=False,          # no-flusher swaps flusher for busybox
        ),
        purpose="Pre-everything baseline image (reverts A+B+D+F) — headline 'before' side",
    ),
    SuiteEntry(
        scenario="national_medium",
        disable_pgbouncer=True,
        output_name="national_medium",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="off",
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="Current-tree mixed traffic — headline 'after' side",
    ),

    # ---- PgBouncer A-comparison: current-tree, with vs without PgBouncer ---
    # The 'with PgBouncer' side runs the same scenario JSON but lets the base
    # compose's default routing through benchmark-pgbouncer stand (no overlay).
    # output_name is suffixed so it doesn't collide with the no-PgBouncer side.
    SuiteEntry(
        scenario="national_medium",
        disable_pgbouncer=False,
        output_name="national_medium_with_pgbouncer",
        expected=Expected(
            pgbouncer_bypassed=False,
            pg_synchronous_commit="off",
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="National medium WITH PgBouncer — A-comparison side at medium adoption",
    ),
    SuiteEntry(
        scenario="national_high",
        disable_pgbouncer=True,
        output_name="national_high",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="off",
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="National high adoption (no PgBouncer) — high-load reference",
    ),
    SuiteEntry(
        scenario="national_high",
        disable_pgbouncer=False,
        output_name="national_high_with_pgbouncer",
        expected=Expected(
            pgbouncer_bypassed=False,
            pg_synchronous_commit="off",
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="National high WITH PgBouncer — A-comparison side at high adoption (PgBouncer's potential niche)",
    ),

    # ---- Marginal optimization comparisons ---------------------------------
    # B (PG tuning): before_pg_tuning_ingest_isolation vs ingest_isolation
    SuiteEntry(
        scenario="before_pg_tuning_ingest_isolation",
        disable_pgbouncer=True,
        output_name="before_pg_tuning_ingest_isolation",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="on",     # pg-defaults reverts B
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="Optimization B baseline (PG stock config)",
    ),
    SuiteEntry(
        scenario="ingest_isolation",
        disable_pgbouncer=True,
        output_name="ingest_isolation",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="off",
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="Current-tree ingest isolation — paired side for B and F comparisons",
    ),
    # D (query cache): before_query_cache_realistic_school_day vs realistic_school_day
    SuiteEntry(
        scenario="before_query_cache_realistic_school_day",
        disable_pgbouncer=True,
        output_name="before_query_cache_realistic_school_day",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="off",
            django_cache_backend="django.core.cache.backends.dummy.DummyCache",
            flusher_running=True,
        ),
        purpose="Optimization D baseline (DummyCache — reverts query cache)",
    ),
    SuiteEntry(
        scenario="realistic_school_day",
        disable_pgbouncer=True,
        output_name="realistic_school_day",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="off",
            django_cache_backend="django_redis.cache.RedisCache",
            flusher_running=True,
        ),
        purpose="Current-tree realistic school day — paired side for D",
    ),
    # F (write buffer + flusher): before_write_buffer_ingest_isolation vs ingest_isolation
    SuiteEntry(
        scenario="before_write_buffer_ingest_isolation",
        disable_pgbouncer=True,
        output_name="before_write_buffer_ingest_isolation",
        expected=Expected(
            pgbouncer_bypassed=True,
            pg_synchronous_commit="off",
            django_cache_backend=None,      # baseline image — cache switch may not be honored
            flusher_running=False,          # no-flusher overlay (the whole point of the F baseline)
        ),
        purpose="Optimization F baseline (no flusher, pre-write-buffer image)",
    ),
]


# -----------------------------------------------------------------------------
# Comparison pairs — invoke compare_reports.py after the suite completes.
# -----------------------------------------------------------------------------
#
# Only declared pairs are compared. Standalone NFR scenarios (endurance_steady,
# lesson_bell_medium, lesson_bell_high, mixed_steady, overload_recovery)
# intentionally do not appear
# here — they have no "before" counterpart and the chapter cites them
# directly from their JSON. Each pair writes to
# ``benchmarks/server_reports/comparison_<name>.md``.
@dataclass
class ComparisonPair:
    name: str            # filename stem for the markdown output
    before: str          # output_name of the 'before' side (must exist in SUITE)
    after: str           # output_name of the 'after' side (must exist in SUITE)
    label_before: str    # human label passed to compare_reports.py
    label_after: str
    purpose: str = ""


COMPARISONS: list[ComparisonPair] = [
    ComparisonPair(
        name="cumulative_before_vs_after",
        before="before_all_optimizations",
        after="national_medium",
        label_before="Pre-everything baseline (A+B+D+F reverted)",
        label_after="Current tree (no PgBouncer)",
        purpose="Headline cumulative effect of A+B+D+F (+ G+H implicitly via current tree)",
    ),
    ComparisonPair(
        name="B_pg_tuning_on_vs_off",
        before="before_pg_tuning_ingest_isolation",
        after="ingest_isolation",
        label_before="PG defaults",
        label_after="PG tuned (sync_commit=off + tuning)",
        purpose="Marginal contribution of optimization B (PG tuning)",
    ),
    ComparisonPair(
        name="D_query_cache_off_vs_on",
        before="before_query_cache_realistic_school_day",
        after="realistic_school_day",
        label_before="DummyCache (no query cache)",
        label_after="django-redis query cache",
        purpose="Marginal contribution of optimization D (query cache)",
    ),
    ComparisonPair(
        name="F_write_buffer_off_vs_on",
        before="before_write_buffer_ingest_isolation",
        after="ingest_isolation",
        label_before="Synchronous ingest (no flusher)",
        label_after="Redis write buffer + flusher",
        purpose="Marginal contribution of optimization F (write buffer)",
    ),
    ComparisonPair(
        name="A_pgbouncer_on_vs_off_national_medium",
        before="national_medium_with_pgbouncer",
        after="national_medium",
        label_before="PgBouncer ON",
        label_after="PgBouncer OFF",
        purpose="A-comparison at medium adoption — confirms PgBouncer is not beneficial at this load",
    ),
    ComparisonPair(
        name="A_pgbouncer_on_vs_off_national_high",
        before="national_high_with_pgbouncer",
        after="national_high",
        label_before="PgBouncer ON",
        label_after="PgBouncer OFF",
        purpose="A-comparison at high adoption — tests whether PgBouncer's niche shows up under heavier load",
    ),
]


# -----------------------------------------------------------------------------
# Pretty printing
# -----------------------------------------------------------------------------

def banner(msg: str, char: str = "=") -> None:
    line = char * 72
    print(f"\n{line}\n{msg}\n{line}", flush=True)


def info(msg: str) -> None:
    print(f"[run_all] {msg}", flush=True)


# -----------------------------------------------------------------------------
# Stack-state verification
# -----------------------------------------------------------------------------

def _pgbouncer_bypassed(backend_env: dict) -> bool:
    """Return True if the backend is bypassing PgBouncer.

    The no-pgbouncer overlay sets DB_HOST=benchmark-db. Any value that is
    not the pgbouncer container name counts as bypassed; an empty/missing
    DB_HOST is treated as "PgBouncer in use" because that's the base
    compose's default routing.
    """
    db_host = (backend_env or {}).get("DB_HOST", "")
    return bool(db_host) and "pgbouncer" not in db_host.lower()


def _flusher_running(flusher_image: str) -> bool:
    """Return True if the flusher container is running the real backend image.

    The no-flusher overlay replaces the image with ``busybox:latest`` and a
    ``sleep infinity`` command. Anything else means the real flusher is up.
    """
    img = (flusher_image or "").lower()
    if not img:
        return False
    return "busybox" not in img


def verify_stack_state(entry: SuiteEntry, scenario_summary: dict) -> list[str]:
    """Compare runtime probe against ``entry.expected``. Returns mismatch list."""
    stack = (scenario_summary or {}).get("stack_state") or {}
    pg = stack.get("postgres_settings") or {}
    env = stack.get("backend_env") or {}
    cache_backend = stack.get("django_cache_backend") or ""
    flusher_image = stack.get("flusher_image") or ""

    mismatches: list[str] = []

    if entry.expected.pgbouncer_bypassed is not None:
        actual = _pgbouncer_bypassed(env)
        if actual != entry.expected.pgbouncer_bypassed:
            mismatches.append(
                f"  pgbouncer_bypassed: expected {entry.expected.pgbouncer_bypassed}, "
                f"got {actual} (DB_HOST={env.get('DB_HOST')!r})"
            )

    if entry.expected.pg_synchronous_commit is not None:
        actual = pg.get("synchronous_commit", "")
        if actual != entry.expected.pg_synchronous_commit:
            mismatches.append(
                f"  pg.synchronous_commit: expected {entry.expected.pg_synchronous_commit!r}, "
                f"got {actual!r}"
            )

    if entry.expected.django_cache_backend is not None:
        # Substring match — full path includes module hierarchy.
        if entry.expected.django_cache_backend not in cache_backend:
            mismatches.append(
                f"  django_cache_backend: expected to contain "
                f"{entry.expected.django_cache_backend!r}, got {cache_backend!r}"
            )

    if entry.expected.flusher_running is not None:
        actual = _flusher_running(flusher_image)
        if actual != entry.expected.flusher_running:
            mismatches.append(
                f"  flusher_running: expected {entry.expected.flusher_running}, "
                f"got {actual} (flusher_image={flusher_image!r})"
            )

    return mismatches


# -----------------------------------------------------------------------------
# Scenario execution
# -----------------------------------------------------------------------------

def scenario_path(entry: SuiteEntry) -> Path:
    p = SCENARIOS_DIR / f"{entry.scenario}.json"
    if not p.is_file():
        raise FileNotFoundError(f"scenario JSON not found: {p}")
    return p


def expected_report_path(entry: SuiteEntry) -> Path:
    """Where run_scenario.py writes the report for this entry.

    run_scenario.py respects ``report_output`` in the scenario JSON (default
    ``benchmarks/reports/<name>.json``) and additionally re-routes under a
    ``no_pgbouncer/`` subdirectory when ``BENCHMARK_DISABLE_PGBOUNCER`` is
    truthy. We reproduce that routing here so we know where to pick up the
    file before moving it to ``server_reports/``.
    """
    with scenario_path(entry).open(encoding="utf-8") as fh:
        scenario = json.load(fh)
    declared = scenario.get("report_output", f"benchmarks/reports/{entry.scenario}.json")
    p = Path(declared)
    if not p.is_absolute():
        p = REPO_ROOT / p
    if entry.disable_pgbouncer:
        p = p.parent / "no_pgbouncer" / p.name
    return p


def final_report_path(entry: SuiteEntry) -> Path:
    return SERVER_REPORTS_DIR / f"{entry.output_name}.json"


def run_one(entry: SuiteEntry, dry_run: bool, skip_existing: bool) -> tuple[bool, list[str]]:
    """Run a single scenario, verify, and move. Returns (ok, mismatches)."""

    final = final_report_path(entry)
    if skip_existing and final.exists():
        info(f"skipping {entry.scenario}: {final} already exists (--skip-existing)")
        return True, []

    cmd = [sys.executable, str(RUN_SCENARIO), str(scenario_path(entry))]

    env = os.environ.copy()
    if entry.disable_pgbouncer:
        env["BENCHMARK_DISABLE_PGBOUNCER"] = "1"
    else:
        # Make doubly sure no leaked value from a prior run is carried in.
        env.pop("BENCHMARK_DISABLE_PGBOUNCER", None)

    banner(f"> {entry.scenario}  ({entry.purpose})", char="=")
    info(f"command: {' '.join(cmd)}")
    info(f"BENCHMARK_DISABLE_PGBOUNCER={env.get('BENCHMARK_DISABLE_PGBOUNCER', '(unset)')}")
    info(f"expected report: {expected_report_path(entry).relative_to(REPO_ROOT)}")
    info(f"final destination: {final.relative_to(REPO_ROOT)}")

    if dry_run:
        info("(dry-run — not executing)")
        return True, []

    started = time.time()
    proc = subprocess.run(cmd, env=env, cwd=str(REPO_ROOT))
    elapsed = time.time() - started
    info(f"run_scenario.py exited with code {proc.returncode} after {elapsed:.0f}s")

    if proc.returncode != 0:
        return False, [f"  run_scenario.py exited non-zero ({proc.returncode})"]

    report_path = expected_report_path(entry)
    if not report_path.is_file():
        return False, [f"  expected report not found at {report_path}"]

    try:
        with report_path.open(encoding="utf-8") as fh:
            report = json.load(fh)
    except json.JSONDecodeError as exc:
        return False, [f"  report at {report_path} is not valid JSON: {exc}"]

    scenario_summary = report.get("scenario_summary") or {}
    mismatches = verify_stack_state(entry, scenario_summary)

    if mismatches:
        info("OVERLAY VERIFICATION FAILED — stack_state does not match expected:")
        for m in mismatches:
            print(m, flush=True)
        return False, mismatches

    info("overlay verification OK")

    SERVER_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if final.exists():
        info(f"overwriting existing {final.relative_to(REPO_ROOT)}")
    shutil.move(str(report_path), str(final))
    info(f"report -> {final.relative_to(REPO_ROOT)}")

    return True, []


# -----------------------------------------------------------------------------
# Comparison execution
# -----------------------------------------------------------------------------

def _output_name_set() -> set[str]:
    return {e.output_name for e in SUITE}


def _validate_comparisons() -> None:
    """Sanity-check at startup that every comparison references known reports."""
    names = _output_name_set()
    for pair in COMPARISONS:
        for side in (pair.before, pair.after):
            if side not in names:
                sys.exit(
                    f"COMPARISONS pair {pair.name!r} references unknown output_name "
                    f"{side!r} — must match a SUITE entry's output_name."
                )


def _comparison_output_path(pair: ComparisonPair) -> Path:
    return SERVER_REPORTS_DIR / f"comparison_{pair.name}.md"


def run_comparisons(dry_run: bool, skip_existing: bool) -> list[tuple[str, str]]:
    """Run compare_reports.py for every pair where both sides exist on disk.

    Returns a list of (pair_name, status) tuples. status is one of:
      "OK" — comparison generated.
      "SKIP_MISSING" — one or both reports missing; pair skipped (not a failure).
      "SKIP_EXISTS"  — comparison already on disk and --skip-existing was passed.
      "FAIL" — compare_reports.py exited non-zero.
    """
    results: list[tuple[str, str]] = []
    for pair in COMPARISONS:
        before_path = SERVER_REPORTS_DIR / f"{pair.before}.json"
        after_path = SERVER_REPORTS_DIR / f"{pair.after}.json"
        out_path = _comparison_output_path(pair)

        banner(f"compare: {pair.name}  ({pair.purpose})", char="-")
        info(f"before: {before_path.relative_to(REPO_ROOT)}")
        info(f"after:  {after_path.relative_to(REPO_ROOT)}")
        info(f"output: {out_path.relative_to(REPO_ROOT)}")

        if not before_path.exists() or not after_path.exists():
            missing = []
            if not before_path.exists():
                missing.append(str(before_path.relative_to(REPO_ROOT)))
            if not after_path.exists():
                missing.append(str(after_path.relative_to(REPO_ROOT)))
            info(f"SKIP — missing: {', '.join(missing)}")
            results.append((pair.name, "SKIP_MISSING"))
            continue

        if skip_existing and out_path.exists():
            info(f"SKIP — comparison already exists (--skip-existing)")
            results.append((pair.name, "SKIP_EXISTS"))
            continue

        cmd = [
            sys.executable, str(COMPARE_REPORTS),
            str(before_path), str(after_path),
            "--label-before", pair.label_before,
            "--label-after", pair.label_after,
            "--output", str(out_path),
        ]
        info(f"command: {' '.join(cmd)}")

        if dry_run:
            info("(dry-run — not executing)")
            results.append((pair.name, "OK"))
            continue

        proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
        if proc.returncode != 0:
            info(f"compare_reports.py exited non-zero ({proc.returncode})")
            results.append((pair.name, "FAIL"))
        else:
            info(f"wrote {out_path.relative_to(REPO_ROOT)}")
            results.append((pair.name, "OK"))

    return results


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def print_plan(entries: list[SuiteEntry]) -> None:
    banner("planned scenarios", char="-")
    for i, e in enumerate(entries, 1):
        marker = " " if e.enabled else "x"
        flag = "no-pgbouncer" if e.disable_pgbouncer else "default"
        print(f"  {marker} {i:>2}. {e.output_name:42s} [{flag:13s}] (scenario: {e.scenario})", flush=True)
        if e.purpose:
            print(f"       {e.purpose}", flush=True)


def print_comparison_plan() -> None:
    banner("planned comparisons (run after the suite)", char="-")
    for i, pair in enumerate(COMPARISONS, 1):
        out = _comparison_output_path(pair).relative_to(REPO_ROOT)
        print(f"  {i:>2}. {pair.name}", flush=True)
        print(f"       {pair.before}  vs  {pair.after}  ->  {out}", flush=True)
        if pair.purpose:
            print(f"       {pair.purpose}", flush=True)


def filter_entries(args) -> list[SuiteEntry]:
    # Filters match on output_name, not scenario, because two entries can share
    # a scenario JSON (e.g. national_medium runs with vs without PgBouncer).
    enabled = [e for e in SUITE if e.enabled]
    if args.only:
        wanted = {name.strip() for name in args.only.split(",") if name.strip()}
        missing = wanted - {e.output_name for e in enabled}
        if missing:
            sys.exit(f"unknown output name(s) for --only: {', '.join(sorted(missing))}")
        enabled = [e for e in enabled if e.output_name in wanted]
    if args.from_:
        names = [e.output_name for e in enabled]
        if args.from_ not in names:
            sys.exit(f"unknown output name for --from: {args.from_}")
        idx = names.index(args.from_)
        enabled = enabled[idx:]
    return enabled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="print the planned suite and exit")
    parser.add_argument("--dry-run", action="store_true", help="print each command without running it")
    parser.add_argument("--only", help="comma-separated list of scenario names to run")
    parser.add_argument("--from", dest="from_", help="resume from this scenario (inclusive)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip scenarios whose final report already exists in server_reports/")
    parser.add_argument("--continue-on-fail", action="store_true",
                        help="log failures and continue to the next scenario instead of aborting")
    parser.add_argument("--skip-comparisons", action="store_true",
                        help="don't run compare_reports.py after the scenarios complete")
    parser.add_argument("--only-comparisons", action="store_true",
                        help="skip the scenario suite entirely and only (re)generate comparisons")
    args = parser.parse_args()

    _validate_comparisons()
    entries = filter_entries(args)

    if args.list:
        print_plan(entries)
        print_comparison_plan()
        return 0

    if not args.only_comparisons:
        print_plan(entries)
    print_comparison_plan()

    scenario_results: list[tuple[str, bool, list[str]]] = []
    if not args.only_comparisons:
        for entry in entries:
            ok, mismatches = run_one(entry, dry_run=args.dry_run, skip_existing=args.skip_existing)
            scenario_results.append((entry.output_name, ok, mismatches))
            if not ok and not args.continue_on_fail:
                banner(f"ABORTING: {entry.output_name} failed", char="!")
                break

    comparison_results: list[tuple[str, str]] = []
    failed_scenarios = [r for r in scenario_results if not r[1]]
    if args.skip_comparisons:
        info("skipping comparison phase (--skip-comparisons)")
    elif failed_scenarios and not args.continue_on_fail:
        info("skipping comparison phase because the suite aborted")
    else:
        comparison_results = run_comparisons(
            dry_run=args.dry_run, skip_existing=args.skip_existing
        )

    banner("summary", char="=")
    if scenario_results:
        print("scenarios:", flush=True)
        for name, ok, mismatches in scenario_results:
            status = "OK" if ok else "FAIL"
            print(f"  [{status}] {name}", flush=True)
            for m in mismatches:
                print(m, flush=True)
    if comparison_results:
        print("comparisons:", flush=True)
        for name, status in comparison_results:
            print(f"  [{status}] {name}", flush=True)

    failed = failed_scenarios + [r for r in comparison_results if r[1] == "FAIL"]
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
