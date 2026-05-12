"""Incremental dashboard rollup updates.

Called by the flusher after a batch of Runs is committed. UPSERTs into the
four rollup tables that the dashboard reads (StudentWeekStats,
StudentWeekLevelStats, ClassroomWeekStats, StudentRunBucketTrend) so the
dashboard can serve current-week data from rollups alone, without reading
hot Run rows.

The weekly compaction (compact_weekly_runs) remains authoritative for
closed weeks — it deletes the rolled-up rows and rebuilds them from raw,
so the incremental updates are eventually replaced with the canonical
full-week aggregate. Incremental + batch must converge to the same values
for that contract to hold; verify_incremental_matches_batch() checks this
on a sample.
"""

from collections import defaultdict

from django.db import connection
from django.db.models import Count
from django.utils import timezone

from .models import (
    Student,
    StudentRunBucketTrend,
    generate_classroom_week_stats_id,
    generate_student_run_bucket_trend_id,
    generate_student_week_level_stats_id,
    generate_student_week_stats_id,
)
from .run_bucket_trends import RUN_BUCKET_SIZE
from .weekly_rollups import week_start_for


def apply_runs_to_dashboard_rollups(runs):
    """UPSERT dashboard rollups for the given freshly-created Runs.

    Must be called inside the same transaction that created the Runs so a
    failure here rolls back the Run inserts too. Empty/no-op for empty
    input.
    """
    if not runs:
        return

    student_meta = _student_meta_for_runs(runs)
    now = timezone.now()

    _upsert_student_week_stats(runs, student_meta, now)
    _upsert_student_week_level_stats(runs, student_meta, now)
    _upsert_classroom_week_stats(runs, student_meta, now)
    _upsert_run_bucket_trends(runs, student_meta, now)


def _student_meta_for_runs(runs):
    """Return {student_id: (classroom_id, teacher_id)} in one query."""
    student_ids = {run.student_id for run in runs}
    return {
        student.id: (student.classroom_id, student.classroom.teacher_id)
        for student in Student.objects.filter(id__in=student_ids).select_related(
            "classroom"
        )
    }


def _aggregate_run_stats(initial=None):
    base = {
        "runs": 0,
        "wins": 0,
        "correct_moves": 0,
        "wrong_moves": 0,
        "score_sum": 0,
        "score_count": 0,
        "score_sum_sq": 0,
        "score_min": None,
        "score_max": None,
        "elapsed_sum_ms": 0,
        "elapsed_count": 0,
        "elapsed_sum_sq": 0,
        "elapsed_min_ms": None,
        "elapsed_max_ms": None,
        "latest_run_id": None,
        "latest_run_created_at": None,
        "first_run_created_at": None,
    }
    if initial:
        base.update(initial)
    return base


def _fold_run_into_stats(stats, run):
    stats["runs"] += 1
    if run.player_won:
        stats["wins"] += 1
    stats["correct_moves"] += run.correct_moves or 0
    stats["wrong_moves"] += run.wrong_moves or 0
    score = run.score or 0
    stats["score_sum"] += score
    stats["score_count"] += 1
    stats["score_sum_sq"] += score * score
    stats["score_min"] = score if stats["score_min"] is None else min(stats["score_min"], score)
    stats["score_max"] = score if stats["score_max"] is None else max(stats["score_max"], score)
    elapsed_ms = run.elapsed_ms or 0
    stats["elapsed_sum_ms"] += elapsed_ms
    stats["elapsed_count"] += 1
    stats["elapsed_sum_sq"] += elapsed_ms * elapsed_ms
    stats["elapsed_min_ms"] = elapsed_ms if stats["elapsed_min_ms"] is None else min(stats["elapsed_min_ms"], elapsed_ms)
    stats["elapsed_max_ms"] = elapsed_ms if stats["elapsed_max_ms"] is None else max(stats["elapsed_max_ms"], elapsed_ms)
    if (
        stats["latest_run_created_at"] is None
        or run.created_at > stats["latest_run_created_at"]
    ):
        stats["latest_run_created_at"] = run.created_at
        stats["latest_run_id"] = run.id
    if (
        stats["first_run_created_at"] is None
        or run.created_at < stats["first_run_created_at"]
    ):
        stats["first_run_created_at"] = run.created_at


# Field tuple used by the StudentWeek* UPSERTs. Order matches both the SQL
# column list and the per-row VALUES tuple, so adding a field is a one-line
# change in three places below.
_RUN_STATS_FIELDS = (
    "runs",
    "wins",
    "correct_moves",
    "wrong_moves",
    "score_sum",
    "score_count",
    "score_sum_sq",
    "score_min",
    "score_max",
    "elapsed_sum_ms",
    "elapsed_count",
    "elapsed_sum_sq",
    "elapsed_min_ms",
    "elapsed_max_ms",
)


def _run_stats_update_clauses(table):
    additive = ",\n  ".join(
        f"{field} = {table}.{field} + EXCLUDED.{field}"
        for field in _RUN_STATS_FIELDS
        if field not in {"score_min", "score_max", "elapsed_min_ms", "elapsed_max_ms"}
    )
    minmax = (
        f"score_min = LEAST({table}.score_min, EXCLUDED.score_min),\n"
        f"  score_max = GREATEST({table}.score_max, EXCLUDED.score_max),\n"
        f"  elapsed_min_ms = LEAST({table}.elapsed_min_ms, EXCLUDED.elapsed_min_ms),\n"
        f"  elapsed_max_ms = GREATEST({table}.elapsed_max_ms, EXCLUDED.elapsed_max_ms)"
    )
    return f"{additive},\n  {minmax}"


def _student_week_clauses():
    table = "digitmileapi_studentweekstats"
    base = _run_stats_update_clauses(table)
    return f"""{base},
  latest_run_id = CASE
    WHEN {table}.latest_run_created_at IS NULL
      OR (EXCLUDED.latest_run_created_at IS NOT NULL
          AND EXCLUDED.latest_run_created_at > {table}.latest_run_created_at)
    THEN EXCLUDED.latest_run_id
    ELSE {table}.latest_run_id
  END,
  latest_run_created_at = GREATEST({table}.latest_run_created_at, EXCLUDED.latest_run_created_at),
  first_run_created_at = LEAST({table}.first_run_created_at, EXCLUDED.first_run_created_at),
  updated_at = EXCLUDED.updated_at"""


def _student_week_level_clauses():
    table = "digitmileapi_studentweeklevelstats"
    base = _run_stats_update_clauses(table)
    return f"""{base},
  latest_run_id = CASE
    WHEN {table}.latest_run_created_at IS NULL
      OR (EXCLUDED.latest_run_created_at IS NOT NULL
          AND EXCLUDED.latest_run_created_at > {table}.latest_run_created_at)
    THEN EXCLUDED.latest_run_id
    ELSE {table}.latest_run_id
  END,
  latest_run_created_at = GREATEST({table}.latest_run_created_at, EXCLUDED.latest_run_created_at),
  updated_at = EXCLUDED.updated_at"""


def _classroom_week_clauses():
    table = "digitmileapi_classroomweekstats"
    additive = ",\n  ".join(
        f"{field} = {table}.{field} + EXCLUDED.{field}"
        for field in (
            "runs",
            "wins",
            "correct_moves",
            "wrong_moves",
            "score_sum",
            "score_count",
            "score_sum_sq",
            "elapsed_sum_ms",
            "elapsed_count",
            "elapsed_sum_sq",
        )
    )
    return f"{additive},\n  updated_at = EXCLUDED.updated_at"


def _upsert_student_week_stats(runs, student_meta, now):
    by_key = {}
    for run in runs:
        if run.student_id not in student_meta:
            continue
        classroom_id, teacher_id = student_meta[run.student_id]
        key = (run.student_id, week_start_for(run.created_at))
        entry = by_key.get(key)
        if entry is None:
            entry = _aggregate_run_stats(
                {
                    "student_id": run.student_id,
                    "classroom_id": classroom_id,
                    "teacher_id": teacher_id,
                    "week_start": key[1],
                }
            )
            by_key[key] = entry
        _fold_run_into_stats(entry, run)

    if not by_key:
        return

    columns = (
        "id",
        "student_id",
        "classroom_id",
        "teacher_id",
        "week_start",
        *_RUN_STATS_FIELDS,
        "latest_run_id",
        "latest_run_created_at",
        "first_run_created_at",
        "created_at",
        "updated_at",
    )
    placeholders = "(" + ", ".join(["%s"] * len(columns)) + ")"
    values = []
    params = []
    for entry in by_key.values():
        values.append(placeholders)
        params.extend(
            [
                generate_student_week_stats_id(),
                entry["student_id"],
                entry["classroom_id"],
                entry["teacher_id"],
                entry["week_start"],
                *[entry[field] for field in _RUN_STATS_FIELDS],
                entry["latest_run_id"],
                entry["latest_run_created_at"],
                entry["first_run_created_at"],
                now,
                now,
            ]
        )

    sql = (
        f"INSERT INTO digitmileapi_studentweekstats ({', '.join(columns)}) "
        f"VALUES {', '.join(values)} "
        f"ON CONFLICT ON CONSTRAINT unique_student_week_stats DO UPDATE SET "
        f"{_student_week_clauses()}"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


def _upsert_student_week_level_stats(runs, student_meta, now):
    by_key = {}
    for run in runs:
        if run.student_id not in student_meta:
            continue
        classroom_id, teacher_id = student_meta[run.student_id]
        key = (run.student_id, week_start_for(run.created_at), run.level)
        entry = by_key.get(key)
        if entry is None:
            entry = _aggregate_run_stats(
                {
                    "student_id": run.student_id,
                    "classroom_id": classroom_id,
                    "teacher_id": teacher_id,
                    "week_start": key[1],
                    "level": run.level,
                }
            )
            by_key[key] = entry
        _fold_run_into_stats(entry, run)

    if not by_key:
        return

    columns = (
        "id",
        "student_id",
        "classroom_id",
        "teacher_id",
        "week_start",
        "level",
        *_RUN_STATS_FIELDS,
        "latest_run_id",
        "latest_run_created_at",
        "created_at",
        "updated_at",
    )
    placeholders = "(" + ", ".join(["%s"] * len(columns)) + ")"
    values = []
    params = []
    for entry in by_key.values():
        values.append(placeholders)
        params.extend(
            [
                generate_student_week_level_stats_id(),
                entry["student_id"],
                entry["classroom_id"],
                entry["teacher_id"],
                entry["week_start"],
                entry["level"],
                *[entry[field] for field in _RUN_STATS_FIELDS],
                entry["latest_run_id"],
                entry["latest_run_created_at"],
                now,
                now,
            ]
        )

    sql = (
        f"INSERT INTO digitmileapi_studentweeklevelstats ({', '.join(columns)}) "
        f"VALUES {', '.join(values)} "
        f"ON CONFLICT ON CONSTRAINT unique_student_week_level_stats DO UPDATE SET "
        f"{_student_week_level_clauses()}"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


def _upsert_classroom_week_stats(runs, student_meta, now):
    by_key = {}
    students_per_classroom_key = defaultdict(set)
    for run in runs:
        if run.student_id not in student_meta:
            continue
        classroom_id, teacher_id = student_meta[run.student_id]
        week_start = week_start_for(run.created_at)
        key = (classroom_id, week_start)
        entry = by_key.get(key)
        if entry is None:
            entry = {
                "classroom_id": classroom_id,
                "teacher_id": teacher_id,
                "week_start": week_start,
                "runs": 0,
                "wins": 0,
                "correct_moves": 0,
                "wrong_moves": 0,
                "score_sum": 0,
                "score_count": 0,
                "score_sum_sq": 0,
                "elapsed_sum_ms": 0,
                "elapsed_count": 0,
                "elapsed_sum_sq": 0,
            }
            by_key[key] = entry
        entry["runs"] += 1
        if run.player_won:
            entry["wins"] += 1
        entry["correct_moves"] += run.correct_moves or 0
        entry["wrong_moves"] += run.wrong_moves or 0
        score = run.score or 0
        entry["score_sum"] += score
        entry["score_count"] += 1
        entry["score_sum_sq"] += score * score
        elapsed_ms = run.elapsed_ms or 0
        entry["elapsed_sum_ms"] += elapsed_ms
        entry["elapsed_count"] += 1
        entry["elapsed_sum_sq"] += elapsed_ms * elapsed_ms
        students_per_classroom_key[key].add(run.student_id)

    if not by_key:
        return

    # student_count on ClassroomWeekStats is the count of distinct students
    # in the classroom *as of the week*. For incremental updates we set it
    # to the current Classroom.students count on first insert (when the row
    # doesn't yet exist). On update we leave it alone — weekly compaction
    # will recompute it authoritatively at end of week.
    classroom_ids = {k[0] for k in by_key.keys()}
    student_counts = {
        entry["classroom_id"]: entry["count"]
        for entry in Student.objects.filter(classroom_id__in=classroom_ids)
        .values("classroom_id")
        .annotate(count=Count("id"))
    }

    columns = (
        "id",
        "classroom_id",
        "teacher_id",
        "week_start",
        "student_count",
        "runs",
        "wins",
        "correct_moves",
        "wrong_moves",
        "score_sum",
        "score_count",
        "score_sum_sq",
        "elapsed_sum_ms",
        "elapsed_count",
        "elapsed_sum_sq",
        "created_at",
        "updated_at",
    )
    placeholders = "(" + ", ".join(["%s"] * len(columns)) + ")"
    values = []
    params = []
    for entry in by_key.values():
        values.append(placeholders)
        params.extend(
            [
                generate_classroom_week_stats_id(),
                entry["classroom_id"],
                entry["teacher_id"],
                entry["week_start"],
                student_counts.get(entry["classroom_id"], 0),
                entry["runs"],
                entry["wins"],
                entry["correct_moves"],
                entry["wrong_moves"],
                entry["score_sum"],
                entry["score_count"],
                entry["score_sum_sq"],
                entry["elapsed_sum_ms"],
                entry["elapsed_count"],
                entry["elapsed_sum_sq"],
                now,
                now,
            ]
        )

    sql = (
        f"INSERT INTO digitmileapi_classroomweekstats ({', '.join(columns)}) "
        f"VALUES {', '.join(values)} "
        f"ON CONFLICT ON CONSTRAINT unique_classroom_week_stats DO UPDATE SET "
        f"{_classroom_week_clauses()}"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


def _upsert_run_bucket_trends(runs, student_meta, now):
    # Group new runs per (student_id, level), sorted by created_at, so we
    # can append to the existing tail bucket in run-arrival order.
    runs_by_pair = defaultdict(list)
    for run in runs:
        if run.student_id not in student_meta:
            continue
        runs_by_pair[(run.student_id, run.level)].append(run)
    for run_list in runs_by_pair.values():
        run_list.sort(key=lambda r: (r.created_at, r.id))

    if not runs_by_pair:
        return

    student_ids = {pair[0] for pair in runs_by_pair.keys()}
    levels = {pair[1] for pair in runs_by_pair.keys()}

    # Tail bucket per (student_id, level). One query fetches all candidate
    # rows; we pick the highest bucket_index per pair in Python.
    tail_by_pair = {}
    for trend in StudentRunBucketTrend.objects.filter(
        student_id__in=student_ids, level__in=levels
    ).order_by("student_id", "level", "-bucket_index"):
        pair = (trend.student_id, trend.level)
        if pair in tail_by_pair:
            continue
        if pair not in runs_by_pair:
            continue
        tail_by_pair[pair] = trend

    # Buckets we'll INSERT (new) or UPSERT-update (existing tail).
    new_rows = []
    updated_rows = []

    for (student_id, level), pair_runs in runs_by_pair.items():
        classroom_id, teacher_id = student_meta[student_id]
        tail = tail_by_pair.get((student_id, level))
        next_index = (tail.bucket_index + 1) if tail else 0

        if tail and tail.run_count < tail.bucket_size_runs:
            slot_room = tail.bucket_size_runs - tail.run_count
            absorbed = pair_runs[:slot_room]
            remaining = pair_runs[slot_room:]
            if absorbed:
                bucket = {
                    "id": tail.id,
                    "student_id": student_id,
                    "classroom_id": classroom_id,
                    "teacher_id": teacher_id,
                    "level": level,
                    "bucket_index": tail.bucket_index,
                    "bucket_size_runs": tail.bucket_size_runs,
                    "first_run_created_at": tail.first_run_created_at,
                    "last_run_created_at": tail.last_run_created_at,
                    "run_count": tail.run_count,
                    "wins": tail.wins,
                    "correct_moves": tail.correct_moves,
                    "wrong_moves": tail.wrong_moves,
                    "score_sum": tail.score_sum,
                    "score_count": tail.score_count,
                    "score_sum_sq": tail.score_sum_sq,
                    "elapsed_sum_ms": tail.elapsed_sum_ms,
                    "elapsed_count": tail.elapsed_count,
                    "elapsed_sum_sq": tail.elapsed_sum_sq,
                }
                for run in absorbed:
                    _accumulate_bucket(bucket, run)
                updated_rows.append(bucket)
        else:
            remaining = pair_runs

        while remaining:
            chunk = remaining[:RUN_BUCKET_SIZE]
            remaining = remaining[RUN_BUCKET_SIZE:]
            bucket = {
                "id": generate_student_run_bucket_trend_id(),
                "student_id": student_id,
                "classroom_id": classroom_id,
                "teacher_id": teacher_id,
                "level": level,
                "bucket_index": next_index,
                "bucket_size_runs": RUN_BUCKET_SIZE,
                "first_run_created_at": chunk[0].created_at,
                "last_run_created_at": chunk[0].created_at,
                "run_count": 0,
                "wins": 0,
                "correct_moves": 0,
                "wrong_moves": 0,
                "score_sum": 0,
                "score_count": 0,
                "score_sum_sq": 0,
                "elapsed_sum_ms": 0,
                "elapsed_count": 0,
                "elapsed_sum_sq": 0,
            }
            for run in chunk:
                _accumulate_bucket(bucket, run)
            new_rows.append(bucket)
            next_index += 1

    # Update the existing tail rows by primary key. One UPDATE per row is
    # simplest and still cheap because there's at most one tail per
    # (student, level) pair in the batch.
    if updated_rows:
        with connection.cursor() as cursor:
            for row in updated_rows:
                cursor.execute(
                    """
                    UPDATE digitmileapi_studentrunbuckettrend
                    SET run_count = %s,
                        wins = %s,
                        correct_moves = %s,
                        wrong_moves = %s,
                        score_sum = %s,
                        score_count = %s,
                        score_sum_sq = %s,
                        elapsed_sum_ms = %s,
                        elapsed_count = %s,
                        elapsed_sum_sq = %s,
                        first_run_created_at = LEAST(first_run_created_at, %s),
                        last_run_created_at = GREATEST(last_run_created_at, %s),
                        updated_at = %s
                    WHERE id = %s
                    """,
                    [
                        row["run_count"],
                        row["wins"],
                        row["correct_moves"],
                        row["wrong_moves"],
                        row["score_sum"],
                        row["score_count"],
                        row["score_sum_sq"],
                        row["elapsed_sum_ms"],
                        row["elapsed_count"],
                        row["elapsed_sum_sq"],
                        row["first_run_created_at"],
                        row["last_run_created_at"],
                        now,
                        row["id"],
                    ],
                )

    if new_rows:
        StudentRunBucketTrend.objects.bulk_create(
            [
                StudentRunBucketTrend(
                    id=row["id"],
                    student_id=row["student_id"],
                    classroom_id=row["classroom_id"],
                    teacher_id=row["teacher_id"],
                    level=row["level"],
                    bucket_index=row["bucket_index"],
                    bucket_size_runs=row["bucket_size_runs"],
                    first_run_created_at=row["first_run_created_at"],
                    last_run_created_at=row["last_run_created_at"],
                    run_count=row["run_count"],
                    wins=row["wins"],
                    correct_moves=row["correct_moves"],
                    wrong_moves=row["wrong_moves"],
                    score_sum=row["score_sum"],
                    score_count=row["score_count"],
                    score_sum_sq=row["score_sum_sq"],
                    elapsed_sum_ms=row["elapsed_sum_ms"],
                    elapsed_count=row["elapsed_count"],
                    elapsed_sum_sq=row["elapsed_sum_sq"],
                )
                for row in new_rows
            ]
        )


def _accumulate_bucket(bucket, run):
    bucket["run_count"] += 1
    if run.player_won:
        bucket["wins"] += 1
    bucket["correct_moves"] += run.correct_moves or 0
    bucket["wrong_moves"] += run.wrong_moves or 0
    score = run.score or 0
    bucket["score_sum"] += score
    bucket["score_count"] += 1
    bucket["score_sum_sq"] += score * score
    elapsed_ms = run.elapsed_ms or 0
    bucket["elapsed_sum_ms"] += elapsed_ms
    bucket["elapsed_count"] += 1
    bucket["elapsed_sum_sq"] += elapsed_ms * elapsed_ms
    bucket["first_run_created_at"] = min(bucket["first_run_created_at"], run.created_at)
    bucket["last_run_created_at"] = max(bucket["last_run_created_at"], run.created_at)
