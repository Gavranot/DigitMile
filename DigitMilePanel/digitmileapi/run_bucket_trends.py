from collections import defaultdict

from django.db import transaction
from django.db.models import Q

from .models import Run, StudentRunBucketTrend


RUN_BUCKET_SIZE = 5


def _default_bucket(run, bucket_index, bucket_size_runs=RUN_BUCKET_SIZE):
    return {
        "student_id": run.student_id,
        "classroom_id": run.student.classroom_id,
        "teacher_id": run.student.classroom.teacher_id,
        "level": run.level,
        "bucket_index": bucket_index,
        "bucket_size_runs": bucket_size_runs,
        "first_run_created_at": run.created_at,
        "last_run_created_at": run.created_at,
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


def _update_bucket_with_run(bucket, run):
    bucket["run_count"] += 1
    bucket["wins"] += 1 if run.player_won else 0
    bucket["correct_moves"] += run.correct_moves or 0
    bucket["wrong_moves"] += run.wrong_moves or 0
    score = run.score or 0
    elapsed_ms = run.elapsed_ms or 0
    bucket["score_sum"] += score
    bucket["score_count"] += 1
    bucket["score_sum_sq"] += score * score
    bucket["elapsed_sum_ms"] += elapsed_ms
    bucket["elapsed_count"] += 1
    bucket["elapsed_sum_sq"] += elapsed_ms * elapsed_ms
    bucket["first_run_created_at"] = min(bucket["first_run_created_at"], run.created_at)
    bucket["last_run_created_at"] = max(bucket["last_run_created_at"], run.created_at)


def _bucket_point(bucket):
    total_moves = bucket["correct_moves"] + bucket["wrong_moves"]
    return {
        "bucket_index": bucket["bucket_index"],
        "bucket_size_runs": bucket["bucket_size_runs"],
        "run_count": bucket["run_count"],
        "wins": bucket["wins"],
        "correct_moves": bucket["correct_moves"],
        "wrong_moves": bucket["wrong_moves"],
        "accuracy": (bucket["correct_moves"] / total_moves * 100)
        if total_moves > 0
        else 0,
        "score": (bucket["score_sum"] / bucket["score_count"])
        if bucket["score_count"] > 0
        else None,
        "time_seconds": (bucket["elapsed_sum_ms"] / bucket["elapsed_count"] / 1000)
        if bucket["elapsed_count"] > 0
        else None,
        "level": bucket["level"],
        "first_run_created_at": bucket["first_run_created_at"],
        "last_run_created_at": bucket["last_run_created_at"],
    }


def _bucket_from_trend(trend):
    return {
        "student_id": trend.student_id,
        "classroom_id": trend.classroom_id,
        "teacher_id": trend.teacher_id,
        "level": trend.level,
        "bucket_index": trend.bucket_index,
        "bucket_size_runs": trend.bucket_size_runs,
        "first_run_created_at": trend.first_run_created_at,
        "last_run_created_at": trend.last_run_created_at,
        "run_count": trend.run_count,
        "wins": trend.wins,
        "correct_moves": trend.correct_moves,
        "wrong_moves": trend.wrong_moves,
        "score_sum": trend.score_sum,
        "score_count": trend.score_count,
        "score_sum_sq": trend.score_sum_sq,
        "elapsed_sum_ms": trend.elapsed_sum_ms,
        "elapsed_count": trend.elapsed_count,
        "elapsed_sum_sq": trend.elapsed_sum_sq,
    }


def rebuild_run_bucket_trends(run_queryset, student_level_pairs=None):
    runs = list(
        run_queryset.select_related("student__classroom__teacher").order_by(
            "student_id", "level", "created_at", "id"
        )
    )
    pairs = set(student_level_pairs or [])
    if not pairs:
        pairs = {(run.student_id, run.level) for run in runs}

    with transaction.atomic():
        for student_id, level in pairs:
            StudentRunBucketTrend.objects.filter(
                student_id=student_id,
                level=level,
            ).delete()

        if not runs:
            return {"student_level_pairs": len(pairs), "bucket_rows": 0, "run_count": 0}

        buckets = []
        current_buckets = {}
        for run in runs:
            key = (run.student_id, run.level)
            bucket = current_buckets.get(key)
            if bucket is None or bucket["run_count"] >= bucket["bucket_size_runs"]:
                bucket_index = 0 if bucket is None else bucket["bucket_index"] + 1
                bucket = _default_bucket(run, bucket_index)
                current_buckets[key] = bucket
                buckets.append(bucket)
            _update_bucket_with_run(bucket, run)

        StudentRunBucketTrend.objects.bulk_create(
            [
                StudentRunBucketTrend(
                    student_id=bucket["student_id"],
                    classroom_id=bucket["classroom_id"],
                    teacher_id=bucket["teacher_id"],
                    level=bucket["level"],
                    bucket_index=bucket["bucket_index"],
                    bucket_size_runs=bucket["bucket_size_runs"],
                    first_run_created_at=bucket["first_run_created_at"],
                    last_run_created_at=bucket["last_run_created_at"],
                    run_count=bucket["run_count"],
                    wins=bucket["wins"],
                    correct_moves=bucket["correct_moves"],
                    wrong_moves=bucket["wrong_moves"],
                    score_sum=bucket["score_sum"],
                    score_count=bucket["score_count"],
                    score_sum_sq=bucket["score_sum_sq"],
                    elapsed_sum_ms=bucket["elapsed_sum_ms"],
                    elapsed_count=bucket["elapsed_count"],
                    elapsed_sum_sq=bucket["elapsed_sum_sq"],
                )
                for bucket in buckets
            ]
        )

    return {
        "student_level_pairs": len(pairs),
        "bucket_rows": len(buckets),
        "run_count": len(runs),
    }


def rebuild_historical_run_bucket_trends(student_level_pairs, include_run_ids=None):
    pairs = set(student_level_pairs)
    if not pairs:
        return {"student_level_pairs": 0, "bucket_rows": 0, "run_count": 0}

    scope = Q()
    for student_id, level in pairs:
        scope |= Q(student_id=student_id, level=level)

    queryset = Run.objects.filter(scope)
    if include_run_ids is not None:
        queryset = queryset.filter(
            Q(raw_data_compacted_at__isnull=False) | Q(id__in=list(include_run_ids))
        )

    return rebuild_run_bucket_trends(
        queryset,
        student_level_pairs=pairs,
    )


def get_student_run_bucket_points(student, level=None):
    trend_queryset = StudentRunBucketTrend.objects.filter(student=student)
    hot_runs_queryset = Run.objects.filter(
        student=student,
        raw_data_compacted_at__isnull=True,
    )

    if level is not None:
        trend_queryset = trend_queryset.filter(level=level)
        hot_runs_queryset = hot_runs_queryset.filter(level=level)

    buckets_by_level = defaultdict(list)
    for trend in trend_queryset.order_by("level", "bucket_index"):
        buckets_by_level[trend.level].append(_bucket_from_trend(trend))

    hot_runs_by_level = defaultdict(list)
    for run in hot_runs_queryset.select_related("student__classroom__teacher").order_by(
        "level", "created_at", "id"
    ):
        hot_runs_by_level[run.level].append(run)

    merged_by_level = {}
    all_levels = set(buckets_by_level.keys()) | set(hot_runs_by_level.keys())
    for bucket_level in sorted(all_levels):
        buckets = list(buckets_by_level.get(bucket_level, []))
        hot_runs = list(hot_runs_by_level.get(bucket_level, []))

        if (
            buckets
            and hot_runs
            and buckets[-1]["run_count"] < buckets[-1]["bucket_size_runs"]
        ):
            tail_bucket = buckets[-1]
            while (
                hot_runs and tail_bucket["run_count"] < tail_bucket["bucket_size_runs"]
            ):
                _update_bucket_with_run(tail_bucket, hot_runs.pop(0))

        next_index = buckets[-1]["bucket_index"] + 1 if buckets else 0
        while hot_runs:
            bucket = _default_bucket(hot_runs[0], next_index)
            while hot_runs and bucket["run_count"] < bucket["bucket_size_runs"]:
                _update_bucket_with_run(bucket, hot_runs.pop(0))
            buckets.append(bucket)
            next_index += 1

        merged_by_level[bucket_level] = [_bucket_point(bucket) for bucket in buckets]

    overall_points = []
    for points in merged_by_level.values():
        overall_points.extend(points)
    overall_points.sort(
        key=lambda point: (
            point["first_run_created_at"],
            point["last_run_created_at"],
            point["level"],
            point["bucket_index"],
        )
    )

    return {
        "points": overall_points,
        "by_level": merged_by_level,
    }
