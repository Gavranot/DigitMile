"""
Compare two scenario reports and print a markdown delta table.

Usage:
    python benchmarks/compare_reports.py <before-report.json> <after-report.json>
    python benchmarks/compare_reports.py <before> <after> --label-before "Pre-PgBouncer" --label-after "Current"

Designed for paired before/after scenarios produced by run_scenario.py
(see benchmarks/scenarios/before_*.json). Both reports must come from
identical dataset + traffic configs; the helper does not check this — if
you compare apples to oranges, the table will still print but the numbers
will be meaningless.
"""

import argparse
import json
import sys
from pathlib import Path


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _pct_delta(before, after):
    if before is None or after is None:
        return None
    try:
        before_f = float(before)
        after_f = float(after)
    except (TypeError, ValueError):
        return None
    if before_f == 0:
        return None
    return round((after_f - before_f) / before_f * 100, 1)


def _fmt(value, suffix=""):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


def _fmt_delta(delta):
    if delta is None:
        return "—"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta}%"


def _safe_get(d, *keys, default=None):
    cur = d
    for key in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int):
            cur = cur[key] if 0 <= key < len(cur) else None
        else:
            return default
    return cur if cur is not None else default


def _first_backend_container_key(resource_summary):
    if not isinstance(resource_summary, dict):
        return None
    for key in resource_summary:
        if "backend" in key:
            return key
    return next(iter(resource_summary), None)


def _find_container_key(resource_summary, *substrings):
    """Return the first container key in resource_summary whose name contains
    any of the given substrings (case-insensitive). Used to locate the role
    containers (backend/db/flusher/redis) without depending on the volatile
    compose-project-name prefix."""
    if not isinstance(resource_summary, dict):
        return None
    for key in resource_summary:
        lowered = key.lower()
        if any(s in lowered for s in substrings):
            return key
    return None


def _container_metric(report, role_substrings, metric_name):
    """Pull a single metric for a role container from a report's resource_summary."""
    rs = report.get("resource_summary", {})
    key = _find_container_key(rs, *role_substrings)
    if key is None:
        return None
    return rs.get(key, {}).get(metric_name)


def _redis_delta(report, field):
    before = _safe_get(report, "redis_stats_before", field, default=0) or 0
    after = _safe_get(report, "redis_stats_after", field, default=0) or 0
    try:
        return int(after) - int(before)
    except (TypeError, ValueError):
        return None


def _row(label, before_val, after_val, suffix=""):
    delta = _pct_delta(before_val, after_val)
    return f"| {label} | {_fmt(before_val, suffix)} | {_fmt(after_val, suffix)} | {_fmt_delta(delta)} |"


def _analytics_rows(before_report, after_report, prefix):
    rows = []
    before_measurements = _safe_get(before_report, prefix, "measurements_ms", default={})
    after_measurements = _safe_get(after_report, prefix, "measurements_ms", default={})
    keys = sorted(set(before_measurements) | set(after_measurements))
    for key in keys:
        before_avg = _safe_get(before_measurements, key, "avg")
        after_avg = _safe_get(after_measurements, key, "avg")
        rows.append(_row(f"{prefix}.{key} avg", before_avg, after_avg, " ms"))
    return rows


def compare(before_path, after_path, label_before, label_after):
    before = _load(before_path)
    after = _load(after_path)

    lines = []
    lines.append(f"# Comparison: {label_before} vs {label_after}")
    lines.append("")
    lines.append(f"- **Before:** `{before_path}` (scenario `{before.get('scenario_name')}`)")
    lines.append(f"- **After:**  `{after_path}` (scenario `{after.get('scenario_name')}`)")
    lines.append("")

    overlays_before = _safe_get(before, "scenario_config", "compose_overlays", default=[])
    overlays_after = _safe_get(after, "scenario_config", "compose_overlays", default=[])
    ref_before = _safe_get(before, "scenario_config", "benchmark_image_ref")
    ref_after = _safe_get(after, "scenario_config", "benchmark_image_ref")
    if overlays_before or overlays_after or ref_before or ref_after:
        lines.append("## Toggle state")
        lines.append("")
        lines.append(f"- Before overlays: `{overlays_before or 'none'}`, image ref: `{ref_before or 'tree HEAD'}`")
        lines.append(f"- After  overlays: `{overlays_after or 'none'}`, image ref: `{ref_after or 'tree HEAD'}`")
        lines.append("")

    lines.append("## Headline")
    lines.append("")
    lines.append("| Metric | Before | After | Δ |")
    lines.append("|---|---|---|---|")
    lines.append(f"| load_health | {before.get('load_health', '—')} | {after.get('load_health', '—')} | — |")

    k6_before = _safe_get(before, "k6_summaries", 0, "highlights", default={})
    k6_after = _safe_get(after, "k6_summaries", 0, "highlights", default={})

    lines.append(_row(
        "http_reqs.rate (sustained RPS)",
        _safe_get(k6_before, "http_reqs", "rate"),
        _safe_get(k6_after, "http_reqs", "rate"),
    ))
    lines.append(_row(
        "http_req_duration.avg",
        _safe_get(k6_before, "http_req_duration", "avg"),
        _safe_get(k6_after, "http_req_duration", "avg"),
        " ms",
    ))
    lines.append(_row(
        "http_req_duration.p(95)",
        _safe_get(k6_before, "http_req_duration", "p(95)"),
        _safe_get(k6_after, "http_req_duration", "p(95)"),
        " ms",
    ))
    lines.append(_row(
        "http_req_duration.p(99)",
        _safe_get(k6_before, "http_req_duration", "p(99)"),
        _safe_get(k6_after, "http_req_duration", "p(99)"),
        " ms",
    ))
    lines.append(_row(
        "dropped_iterations.count",
        _safe_get(k6_before, "dropped_iterations", "count"),
        _safe_get(k6_after, "dropped_iterations", "count"),
    ))
    lines.append(_row(
        "iterations.count (completed)",
        _safe_get(k6_before, "iterations", "count"),
        _safe_get(k6_after, "iterations", "count"),
    ))
    lines.append("")

    lines.append("## Backend container resource usage")
    lines.append("")
    lines.append("| Metric | Before | After | Δ |")
    lines.append("|---|---|---|---|")
    backend_before_key = _first_backend_container_key(before.get("resource_summary", {}))
    backend_after_key = _first_backend_container_key(after.get("resource_summary", {}))
    backend_before = _safe_get(before, "resource_summary", backend_before_key, default={})
    backend_after = _safe_get(after, "resource_summary", backend_after_key, default={})
    lines.append(_row("cpu_percent_avg",
                      backend_before.get("cpu_percent_avg"),
                      backend_after.get("cpu_percent_avg"),
                      "%"))
    lines.append(_row("cpu_percent_peak",
                      backend_before.get("cpu_percent_peak"),
                      backend_after.get("cpu_percent_peak"),
                      "%"))
    lines.append(_row("memory_usage_bytes_peak",
                      backend_before.get("memory_usage_bytes_peak"),
                      backend_after.get("memory_usage_bytes_peak")))
    lines.append("")

    lines.append("## Pipeline & resources")
    lines.append("")
    lines.append("Surfaces what the HTTP-side latency table can't show: how the async write")
    lines.append("path (flusher), the database, and Redis behave under the same workload.")
    lines.append("")

    # Backend
    lines.append("### Backend container")
    lines.append("")
    lines.append("| Metric | Before | After | Δ |")
    lines.append("|---|---|---|---|")
    for metric, label, suffix in [
        ("cpu_percent_avg", "cpu_percent_avg", "%"),
        ("cpu_percent_peak", "cpu_percent_peak", "%"),
        ("memory_usage_bytes_avg", "memory_usage_bytes_avg", ""),
        ("memory_usage_bytes_peak", "memory_usage_bytes_peak", ""),
    ]:
        lines.append(_row(
            label,
            _container_metric(before, ("backend",), metric),
            _container_metric(after, ("backend",), metric),
            suffix,
        ))
    lines.append("")

    # Flusher (async write path)
    flusher_present = (
        _container_metric(before, ("flusher",), "cpu_percent_avg") is not None
        or _container_metric(after, ("flusher",), "cpu_percent_avg") is not None
    )
    if flusher_present:
        lines.append("### Flusher (async write path)")
        lines.append("")
        lines.append("Same workload should drive similar flusher CPU. Large gaps imply the")
        lines.append("flusher is either backlogging (buffer growing) or starved (low CPU,")
        lines.append("high backend pressure). Memory peak proxies how deep the buffer got.")
        lines.append("")
        lines.append("| Metric | Before | After | Δ |")
        lines.append("|---|---|---|---|")
        for metric, label, suffix in [
            ("cpu_percent_avg", "cpu_percent_avg", "%"),
            ("cpu_percent_peak", "cpu_percent_peak", "%"),
            ("memory_usage_bytes_peak", "memory_usage_bytes_peak", ""),
        ]:
            lines.append(_row(
                label,
                _container_metric(before, ("flusher",), metric),
                _container_metric(after, ("flusher",), metric),
                suffix,
            ))
        lines.append("")

    # Database
    lines.append("### Database (PostgreSQL)")
    lines.append("")
    lines.append("Reflects how much real write work the flusher pushed to PG. Higher db CPU")
    lines.append("with the same HTTP throughput is *good* — more rows actually committed.")
    lines.append("")
    lines.append("| Metric | Before | After | Δ |")
    lines.append("|---|---|---|---|")
    for metric, label, suffix in [
        ("cpu_percent_avg", "cpu_percent_avg", "%"),
        ("cpu_percent_peak", "cpu_percent_peak", "%"),
    ]:
        lines.append(_row(
            label,
            _container_metric(before, ("-db-", "postgres"), metric),
            _container_metric(after, ("-db-", "postgres"), metric),
            suffix,
        ))
    lines.append("")

    # Redis throughput
    lines.append("### Redis throughput")
    lines.append("")
    lines.append("`total_commands_processed` delta is a proxy for end-to-end pipeline activity:")
    lines.append("LPUSH from the HTTP path + LRANGE/LTRIM from the flusher + cache GETs/SETs.")
    lines.append("Higher = more data moved through the full ingest path in the same window.")
    lines.append("")
    lines.append("| Metric | Before | After | Δ |")
    lines.append("|---|---|---|---|")
    lines.append(_row(
        "total_commands_processed (Δ during run)",
        _redis_delta(before, "total_commands_processed"),
        _redis_delta(after, "total_commands_processed"),
    ))
    lines.append(_row(
        "cache hits",
        _safe_get(before, "redis_cache_summary", "hits"),
        _safe_get(after, "redis_cache_summary", "hits"),
    ))
    lines.append(_row(
        "cache misses",
        _safe_get(before, "redis_cache_summary", "misses"),
        _safe_get(after, "redis_cache_summary", "misses"),
    ))
    lines.append(_row(
        "cache hit_rate_pct",
        _safe_get(before, "redis_cache_summary", "hit_rate_pct"),
        _safe_get(after, "redis_cache_summary", "hit_rate_pct"),
        "%",
    ))
    lines.append("")

    analytics_rows = _analytics_rows(before, after, "pre_benchmark")
    if analytics_rows:
        lines.append("## Analytics latency — pre-traffic baseline (idle DB)")
        lines.append("")
        lines.append("| Metric | Before | After | Δ |")
        lines.append("|---|---|---|---|")
        lines.extend(analytics_rows)
        lines.append("")

    post_rows = _analytics_rows(before, after, "post_benchmark")
    if post_rows:
        lines.append("## Analytics latency — post-traffic")
        lines.append("")
        lines.append("| Metric | Before | After | Δ |")
        lines.append("|---|---|---|---|")
        lines.extend(post_rows)
        lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.append("- Δ is `(after − before) / before × 100`. Negative Δ on latency = improvement;")
    lines.append("  positive Δ on RPS / iterations = improvement.")
    lines.append("- If either side is `red`, latency numbers are not representative — see the")
    lines.append("  `load_health` note in each report.")
    lines.append("- Dataset and traffic shape are assumed identical. Re-check both scenario JSONs")
    lines.append("  if any number looks impossibly large.")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compare two scenario reports.")
    parser.add_argument("before", help="Path to the 'before' report JSON")
    parser.add_argument("after", help="Path to the 'after' report JSON")
    parser.add_argument("--label-before", default="Before", help="Human label for the before report")
    parser.add_argument("--label-after", default="After", help="Human label for the after report")
    parser.add_argument("--output", help="Optional path to write the markdown report to (default: stdout)")
    args = parser.parse_args()

    markdown = compare(args.before, args.after, args.label_before, args.label_after)
    if args.output:
        Path(args.output).write_text(markdown + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(markdown)


if __name__ == "__main__":
    main()
