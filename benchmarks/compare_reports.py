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
