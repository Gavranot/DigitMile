from datetime import date, datetime, timedelta
import math


DECISION_TIME_CLIP_CEILING_MS = 120000


def week_start_for(value):
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        raise TypeError("week_start_for expects a date or datetime")
    return value - timedelta(days=value.weekday())


def week_end_for(value):
    return week_start_for(value) + timedelta(days=6)


def average_from_sum_count(total, count):
    if count <= 0:
        return 0
    return total / count


def sample_variance_from_stats(total, total_sq, count):
    if count <= 1:
        return 0

    numerator = total_sq - ((total * total) / count)
    variance = numerator / (count - 1)
    return max(0, variance)


def sample_stddev_from_stats(total, total_sq, count):
    return math.sqrt(sample_variance_from_stats(total, total_sq, count))


def clip_decision_time_ms(value, ceiling=DECISION_TIME_CLIP_CEILING_MS):
    clipped_value = min(value, ceiling)
    return clipped_value, value > ceiling
