import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_COMPOSE_FILE = REPO_ROOT / "benchmarks" / "docker-compose.benchmark.yml"
BENCHMARK_BACKEND_SERVICE = "benchmark-backend"
BENCHMARK_DB_SERVICE = "benchmark-db"
K6_IMAGE = "grafana/k6:0.49.0"
K6_CONTAINER_NAME = "digitmile-k6-runner"
BYTE_UNITS = {
    "B": 1,
    "kB": 1000,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "KiB": 1024,
    "MiB": 1024**2,
    "GiB": 1024**3,
    "TiB": 1024**4,
}
HEARTBEAT_INTERVAL_SECONDS = 60


def log_step(message):
    print(f"[run_scenario] {message}", flush=True)


def write_console(text):
    safe_text = text.encode("ascii", errors="backslashreplace").decode("ascii")
    sys.stdout.write(safe_text)
    sys.stdout.flush()


def _format_duration(seconds):
    total_seconds = max(0, int(seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {remaining_minutes}m {remaining_seconds}s"
    if minutes:
        return f"{minutes}m {remaining_seconds}s"
    return f"{remaining_seconds}s"


def run_command(command, *, cwd=REPO_ROOT, check=True):
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
    )


def stream_command(command, *, cwd=REPO_ROOT, heartbeat_label="command"):
    process = subprocess.Popen(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output = []
    if process.stdout is None:
        raise RuntimeError("Process stdout stream was not created")
    started_at = time.time()
    activity = {
        "last_output_at": started_at,
        "last_heartbeat_at": 0.0,
    }
    output_thread = threading.Thread(
        target=_pump_process_output,
        args=(process.stdout, output, activity),
        daemon=True,
    )
    output_thread.start()
    try:
        while process.poll() is None:
            current_time = time.time()
            quiet_for_seconds = current_time - activity["last_output_at"]
            since_last_heartbeat = current_time - activity["last_heartbeat_at"]
            if (
                quiet_for_seconds >= HEARTBEAT_INTERVAL_SECONDS
                and since_last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS
            ):
                log_step(
                    f"still running {heartbeat_label}; elapsed {_format_duration(current_time - started_at)}; last output {_format_duration(quiet_for_seconds)} ago"
                )
                activity["last_heartbeat_at"] = current_time
            time.sleep(1)
    finally:
        process.wait()
        output_thread.join(timeout=5)
    return_code = process.wait()
    combined_output = "".join(output)
    if return_code != 0:
        raise subprocess.CalledProcessError(
            return_code, command, output=combined_output
        )
    return combined_output


def compose_command(project_name, *args):
    return [
        "docker",
        "compose",
        "-f",
        str(BENCHMARK_COMPOSE_FILE),
        "-p",
        project_name,
        *args,
    ]


def compose_up(project_name):
    log_step(f"starting isolated benchmark stack {project_name}")
    stream_command(
        compose_command(
            project_name,
            "up",
            "-d",
            "--build",
            BENCHMARK_DB_SERVICE,
            BENCHMARK_BACKEND_SERVICE,
        ),
        heartbeat_label=f"docker compose up for {project_name}",
    )


def compose_down(project_name):
    run_command(
        compose_command(project_name, "down", "-v", "--remove-orphans"),
        check=False,
    )


def compose_exec(project_name, service_name, *args):
    return run_command(compose_command(project_name, "exec", "-T", service_name, *args))


def compose_exec_stream(project_name, service_name, *args):
    return stream_command(
        compose_command(project_name, "exec", "-T", service_name, *args),
        heartbeat_label=f"docker compose exec {service_name}",
    )


def compose_service_container_id(project_name, service_name):
    result = run_command(compose_command(project_name, "ps", "-q", service_name))
    return result.stdout.strip()


def container_cp_from(container_id, container_path, host_path):
    run_command(["docker", "cp", f"{container_id}:{container_path}", str(host_path)])


def docker_network_for_container(container_id):
    result = run_command(
        [
            "docker",
            "inspect",
            container_id,
            "--format",
            "{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}",
        ]
    )
    return result.stdout.strip()


def container_state(container_id):
    result = run_command(
        [
            "docker",
            "inspect",
            container_id,
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
        ]
    )
    return result.stdout.strip()


def wait_for_backend_ready(project_name, timeout_seconds=300):
    deadline = time.time() + timeout_seconds
    last_status = None
    while time.time() < deadline:
        container_id = compose_service_container_id(
            project_name, BENCHMARK_BACKEND_SERVICE
        )
        if container_id:
            status_value = container_state(container_id)
            if status_value != last_status:
                log_step(f"benchmark backend status: {status_value}")
                last_status = status_value
            if status_value == "healthy":
                return container_id
        time.sleep(2)
    raise RuntimeError("Timed out waiting for benchmark backend to become healthy")


def docker_stats(container_ids):
    result = run_command(
        ["docker", "stats", "--no-stream", "--format", "{{ json . }}", *container_ids]
    )
    stats = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            stats.append(json.loads(line))
    return stats


def parse_percent(value):
    if not value:
        return None
    return round(float(str(value).replace("%", "").strip()), 2)


def parse_human_bytes(value):
    if not value:
        return None
    match = re.match(r"^\s*([0-9.]+)\s*([A-Za-z]+)\s*$", str(value))
    if not match:
        return None
    multiplier = BYTE_UNITS.get(match.group(2))
    if multiplier is None:
        return None
    return round(float(match.group(1)) * multiplier, 2)


def parse_memory_usage(value):
    used, _, limit = str(value or "").partition("/")
    return parse_human_bytes(used.strip()), parse_human_bytes(limit.strip())


def parse_pids(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def collect_runtime_sample(container_ids, started_at):
    raw_stats = docker_stats(container_ids)
    sample = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - started_at, 2),
        "containers": {},
    }
    for raw in raw_stats:
        memory_used, memory_limit = parse_memory_usage(raw.get("MemUsage"))
        sample["containers"][raw.get("Name", "unknown")] = {
            "cpu_percent": parse_percent(raw.get("CPUPerc")),
            "memory_percent": parse_percent(raw.get("MemPerc")),
            "memory_usage_bytes": memory_used,
            "memory_limit_bytes": memory_limit,
            "pids": parse_pids(raw.get("PIDs")),
            "raw": raw,
        }
    return sample


def summarize_runtime_samples(samples):
    summary = {}
    for sample in samples:
        for container_name, container_stats in sample.get("containers", {}).items():
            bucket = summary.setdefault(
                container_name,
                {
                    "sample_count": 0,
                    "cpu_percent_total": 0.0,
                    "cpu_percent_peak": 0.0,
                    "memory_usage_bytes_total": 0.0,
                    "memory_usage_bytes_peak": 0.0,
                    "memory_percent_peak": 0.0,
                },
            )
            bucket["sample_count"] += 1
            cpu_percent = container_stats.get("cpu_percent") or 0.0
            memory_usage_bytes = container_stats.get("memory_usage_bytes") or 0.0
            memory_percent = container_stats.get("memory_percent") or 0.0
            bucket["cpu_percent_total"] += cpu_percent
            bucket["memory_usage_bytes_total"] += memory_usage_bytes
            bucket["cpu_percent_peak"] = max(bucket["cpu_percent_peak"], cpu_percent)
            bucket["memory_usage_bytes_peak"] = max(
                bucket["memory_usage_bytes_peak"], memory_usage_bytes
            )
            bucket["memory_percent_peak"] = max(
                bucket["memory_percent_peak"], memory_percent
            )

    for bucket in summary.values():
        sample_count = bucket["sample_count"] or 1
        bucket["cpu_percent_avg"] = round(
            bucket.pop("cpu_percent_total") / sample_count, 2
        )
        bucket["memory_usage_bytes_avg"] = round(
            bucket.pop("memory_usage_bytes_total") / sample_count,
            2,
        )
    return summary


def ensure_k6_container(network_name):
    run_command(["docker", "rm", "-f", K6_CONTAINER_NAME], check=False)
    run_command(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            K6_CONTAINER_NAME,
            "--entrypoint",
            "sh",
            "--network",
            network_name,
            "--add-host",
            "host.docker.internal:host-gateway",
            "-v",
            f"{REPO_ROOT / 'benchmarks'}:/benchmarks",
            "-w",
            "/benchmarks",
            K6_IMAGE,
            "-c",
            "sleep infinity",
        ]
    )


def cleanup_k6_container():
    run_command(["docker", "rm", "-f", K6_CONTAINER_NAME], check=False)


def build_k6_exec_command(script_path, summary_path, env_map):
    command = ["docker", "exec"]
    for key, value in env_map.items():
        if value is None:
            continue
        command.extend(["-e", f"{key}={value}"])
    command.extend(
        [
            K6_CONTAINER_NAME,
            "k6",
            "run",
            str(script_path),
            "--summary-export",
            str(summary_path),
        ]
    )
    return command


def _pump_process_output(stream, buffer, activity):
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            buffer.append(line)
            activity["last_output_at"] = time.time()
            write_console(line)
    finally:
        stream.close()


def run_k6_with_sampling(
    script_path, summary_path, env_map, sample_interval_seconds, container_ids
):
    log_step(
        f"starting k6 script {Path(script_path).name} with duration {env_map.get('DURATION', 'unknown')}"
    )
    command = build_k6_exec_command(script_path, summary_path, env_map)
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    if process.stdout is None:
        raise RuntimeError("k6 process stdout stream was not created")
    started_at = time.time()
    next_sample_at = started_at
    runtime_samples = []
    output_buffer = []
    activity = {
        "last_output_at": started_at,
        "last_heartbeat_at": 0.0,
    }
    output_thread = threading.Thread(
        target=_pump_process_output,
        args=(process.stdout, output_buffer, activity),
        daemon=True,
    )
    output_thread.start()

    while process.poll() is None:
        current_time = time.time()
        quiet_for_seconds = current_time - activity["last_output_at"]
        since_last_heartbeat = current_time - activity["last_heartbeat_at"]
        if (
            quiet_for_seconds >= HEARTBEAT_INTERVAL_SECONDS
            and since_last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS
        ):
            log_step(
                f"still running k6 script {Path(script_path).name}; elapsed {_format_duration(current_time - started_at)}; last output {_format_duration(quiet_for_seconds)} ago"
            )
            activity["last_heartbeat_at"] = current_time
        if current_time >= next_sample_at:
            runtime_samples.append(collect_runtime_sample(container_ids, started_at))
            next_sample_at = current_time + sample_interval_seconds
        time.sleep(0.5)

    runtime_samples.append(collect_runtime_sample(container_ids, started_at))
    process.wait()
    output_thread.join(timeout=5)
    stdout = "".join(output_buffer)
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, command, output=stdout)
    return {
        "stdout": stdout,
        "runtime_samples": runtime_samples,
        "resource_summary": summarize_runtime_samples(runtime_samples),
    }


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def extract_k6_highlights(summary):
    metrics = summary.get("metrics", {})
    extracted = {}
    for metric_name in [
        "http_req_duration",
        "http_req_failed",
        "http_reqs",
        "dropped_iterations",
        "iterations",
        "vus_max",
    ]:
        metric = metrics.get(metric_name, {})
        extracted[metric_name] = metric.get("values", metric)
    return extracted


def extract_check_results(summary):
    """Extract pass/fail counts from k6 root_group.checks."""
    checks = summary.get("root_group", {}).get("checks", {})
    total_passes = 0
    total_fails = 0
    by_check = {}
    for check_name, check_data in checks.items():
        passes = check_data.get("passes", 0)
        fails = check_data.get("fails", 0)
        total_passes += passes
        total_fails += fails
        by_check[check_name] = {"passes": passes, "fails": fails}
    return {"passes": total_passes, "fails": total_fails, "by_check": by_check}


def assess_load_health(highlights, checks_summary):
    """
    Produce a green / yellow / red health indicator for a k6 run.

    green  - no drops, no check failures; latency numbers are fully reliable.
    yellow - up to 5% drops or 2% check failures; results are usable with caveats.
    red    - server over capacity; latency numbers only reflect the requests that
             got through and must not be used to draw conclusions about the server.
    """
    dropped_data = highlights.get("dropped_iterations") or {}
    dropped = dropped_data.get("count", 0)

    iterations_data = highlights.get("iterations") or {}
    completed = iterations_data.get("count", 0)

    total_attempted = completed + dropped
    drop_rate = round(dropped / max(1, total_attempted), 4) if total_attempted > 0 else 0.0

    check_passes = checks_summary.get("passes", 0)
    check_fails = checks_summary.get("fails", 0)
    total_checks = check_passes + check_fails
    check_fail_rate = round(check_fails / max(1, total_checks), 4) if total_checks > 0 else 0.0

    if drop_rate == 0 and check_fail_rate == 0:
        status = "green"
        note = (
            "Server handled this load without drops or failures. "
            "Latency numbers reflect the true cost of each request."
        )
    elif drop_rate < 0.05 and check_fail_rate < 0.02:
        status = "yellow"
        note = (
            f"Marginal load: {drop_rate:.1%} of planned iterations were dropped. "
            "Latency numbers may be slightly optimistic because slow requests that "
            "never started are not counted. Consider reducing rates for a cleaner baseline."
        )
    else:
        status = "red"
        note = (
            f"Server over capacity: {drop_rate:.1%} of iterations dropped, "
            f"{check_fail_rate:.1%} of checks failed. "
            "Latency numbers represent only the requests that got through and are "
            "not representative of what the server would do at realistic load. "
            "Reduce rates significantly before drawing conclusions."
        )

    return {
        "status": status,
        "note": note,
        "dropped_iterations": dropped,
        "completed_iterations": completed,
        "total_attempted": total_attempted,
        "drop_rate": drop_rate,
        "check_passes": check_passes,
        "check_fails": check_fails,
        "check_fail_rate": check_fail_rate,
    }


def compose_project_name(scenario_name):
    cleaned = re.sub(r"[^a-z0-9]+", "-", scenario_name.lower()).strip("-")
    return f"digitmile-bench-{cleaned}"[:63]


def ensure_backend_image():
    result = run_command(
        ["docker", "image", "inspect", "gashmurble/digitmile-backend:prod-latest"],
        check=False,
    )
    if result.returncode == 0:
        return True

    log_step("benchmark backend image missing;")
    return False

def should_keep_stack_on_failure():
    return os.getenv("BENCHMARK_KEEP_STACK", "0") == "1"


def main():
    parser = argparse.ArgumentParser(description="Run a benchmark scenario")
    parser.add_argument("scenario", help="Path to scenario JSON file")
    args = parser.parse_args()

    scenario_path = Path(args.scenario)
    if not scenario_path.is_absolute():
        scenario_path = REPO_ROOT / scenario_path
    scenario = load_json(scenario_path)

    report_output = scenario.get(
        "report_output", "benchmarks/reports/scenario-report.json"
    )
    report_output_path = Path(report_output)
    if not report_output_path.is_absolute():
        report_output_path = REPO_ROOT / report_output_path
    report_output_path.parent.mkdir(parents=True, exist_ok=True)

    scenario_name = scenario.get("name", scenario_path.stem)
    project_name = compose_project_name(scenario_name)
    log_step(f"loaded scenario {scenario_name} from {scenario_path}")
    log_step(f"using isolated compose project {project_name}")
    scenario_report_dir = report_output_path.parent / f"{scenario_name}_artifacts"
    scenario_report_dir.mkdir(parents=True, exist_ok=True)

    backend_container_id = None
    db_container_id = None
    keep_stack = False

    try:
        if not ensure_backend_image():
            return
        compose_up(project_name)
        backend_container_id = wait_for_backend_ready(project_name)
        db_container_id = compose_service_container_id(
            project_name, BENCHMARK_DB_SERVICE
        )
        network_name = docker_network_for_container(backend_container_id)
        ensure_k6_container(network_name)

        dataset = scenario["dataset"]
        dataset_container_path = f"/tmp/{scenario_name}_dataset.json"
        dataset_args = [
            "prepare_benchmark_dataset",
            "--teachers",
            str(dataset["teachers"]),
            "--classrooms-per-teacher",
            str(dataset["classrooms_per_teacher"]),
            "--students-per-classroom",
            str(dataset["students_per_classroom"]),
            "--weeks",
            str(dataset["weeks"]),
            "--runs-per-student-per-week",
            str(dataset["runs_per_student_per_week"]),
            "--avg-turns-per-run",
            str(dataset["avg_turns_per_run"]),
            "--card-mix-profile",
            dataset["card_mix_profile"],
            "--bag-level-ratio",
            str(dataset["bag_level_ratio"]),
            "--hot-weeks",
            str(dataset["hot_weeks"]),
            "--output",
            dataset_container_path,
            "--clear",
        ]
        if dataset.get("compact_weeks"):
            dataset_args.extend(["--compact-weeks", str(dataset["compact_weeks"])])
        if dataset.get("anchor_week_start"):
            dataset_args.extend(["--anchor-week-start", dataset["anchor_week_start"]])

        dataset_begin = time.perf_counter()
        log_step("preparing benchmark dataset")
        compose_exec_stream(
            project_name,
            BENCHMARK_BACKEND_SERVICE,
            "python",
            "manage.py",
            *dataset_args,
        )
        log_step(f"dataset ready in {round((time.perf_counter() - dataset_begin), 2)}s")
        dataset_report_path = scenario_report_dir / "dataset.json"
        container_cp_from(
            backend_container_id, dataset_container_path, dataset_report_path
        )
        dataset_report = load_json(dataset_report_path)
        first_teacher = dataset_report["teachers"][0]

        benchmark_iterations = str(
            scenario.get("verification", {}).get("benchmark_iterations", 5)
        )
        pre_benchmark_path = scenario_report_dir / "benchmark_pre.json"
        pre_benchmark_container_path = f"/tmp/{scenario_name}_benchmark_pre.json"
        pre_benchmark_begin = time.perf_counter()
        log_step("running pre-traffic analytics benchmark")
        compose_exec(
            project_name,
            BENCHMARK_BACKEND_SERVICE,
            "python",
            "manage.py",
            "benchmark_teacher_analytics",
            str(first_teacher["teacher_id"]),
            "--iterations",
            benchmark_iterations,
            "--scenario-name",
            f"{scenario_name}_pre",
            "--output",
            pre_benchmark_container_path,
        )
        log_step(
            f"pre-traffic analytics benchmark done in {round((time.perf_counter() - pre_benchmark_begin), 2)}s"
        )
        container_cp_from(
            backend_container_id, pre_benchmark_container_path, pre_benchmark_path
        )
        pre_benchmark = load_json(pre_benchmark_path)

        traffic = scenario.get("traffic", {})
        env_map = {
            "BASE_URL": traffic.get("base_url", "http://benchmark-backend:8000"),
            "REQUEST_HOST_HEADER": traffic.get("request_host_header", "localhost"),
            "TEACHER_USERNAME": first_teacher["username"],
            "TEACHER_PASSWORD": dataset_report["teacher_password"],
            "VUS_PLAYERS": str(traffic.get("vus_players", 5)),
            "VUS_TEACHERS": str(traffic.get("vus_teachers", 3)),
            "DURATION": traffic.get("duration", "30s"),
            "HOT_REPLAY_RATIO": str(traffic.get("hot_replay_ratio", 0.3)),
            "GRADE_FILTER_RATIO": str(traffic.get("grade_filter_ratio", 0.3)),
            "CLASSROOM_FILTER_RATIO": str(traffic.get("classroom_filter_ratio", 0.3)),
            "SCENARIO_NAME": scenario_name,
            "USE_ARRIVAL_RATE": "1" if traffic.get("use_arrival_rate") else "0",
            "INGEST_RATE_PER_SEC": str(traffic.get("ingest_rate_per_sec", 8)),
            "DASHBOARD_RATE_PER_SEC": str(traffic.get("dashboard_rate_per_sec", 4)),
            "ANALYTICS_RATE_PER_SEC": str(traffic.get("analytics_rate_per_sec", 3)),
            "TURN_INSIGHTS_RATE_PER_SEC": str(
                traffic.get("turn_insights_rate_per_sec", 3)
            ),
            "REPLAY_RATE_PER_SEC": str(traffic.get("replay_rate_per_sec", 2)),
            "INGEST_EXPECTED_MODE": traffic.get("ingest_expected_mode", "accepted"),
            "BENCHMARK_REFERENCE_TIME": traffic.get(
                "benchmark_reference_time",
                dataset_report.get("synthetic_now"),
            ),
            "RAMP_MODE": "1" if traffic.get("ramp_mode") else "0",
        }
        # Pass explicit per-class VU overrides from the scenario JSON so that
        # the scenario config is the single source of truth for VU sizing.
        for _cls, _key in [
            ("INGEST", "ingest"),
            ("DASHBOARD", "dashboard"),
            ("ANALYTICS", "analytics"),
            ("TURN_INSIGHTS", "turn_insights"),
            ("REPLAY", "replay"),
        ]:
            pre = traffic.get(f"{_key}_pre_allocated_vus")
            max_v = traffic.get(f"{_key}_max_vus")
            if pre is not None:
                env_map[f"{_cls}_PRE_ALLOCATED_VUS"] = str(pre)
            if max_v is not None:
                env_map[f"{_cls}_MAX_VUS"] = str(max_v)
        sample_interval_seconds = float(
            traffic.get("resource_sample_interval_seconds", 3)
        )
        runtime_container_ids = [backend_container_id, db_container_id]

        log_step("capturing baseline container stats")
        docker_stats_before = docker_stats(runtime_container_ids)
        k6_summaries = []
        all_runtime_samples = []
        for script_name in traffic.get("scripts", []):
            summary_path = (
                scenario_report_dir / f"{Path(script_name).stem}_summary.json"
            )
            script_path = f"/benchmarks/k6/{script_name}"
            container_summary_path = "/benchmarks/" + str(
                summary_path.relative_to(REPO_ROOT / "benchmarks")
            ).replace("\\", "/")
            container_env_map = dict(env_map)
            container_env_map["DATASET_REPORT"] = "/benchmarks/" + str(
                dataset_report_path.relative_to(REPO_ROOT / "benchmarks")
            ).replace("\\", "/")
            container_env_map["SCENARIO_CONFIG"] = "/benchmarks/" + str(
                scenario_path.relative_to(REPO_ROOT / "benchmarks")
            ).replace("\\", "/")
            script_begin = time.perf_counter()
            k6_result = run_k6_with_sampling(
                script_path,
                container_summary_path,
                container_env_map,
                sample_interval_seconds,
                runtime_container_ids,
            )
            log_step(
                f"k6 script {script_name} finished in {round((time.perf_counter() - script_begin), 2)}s"
            )
            summary = load_json(summary_path)
            all_runtime_samples.extend(k6_result["runtime_samples"])
            highlights = extract_k6_highlights(summary)
            check_results = extract_check_results(summary)
            k6_summaries.append(
                {
                    "script": script_name,
                    "summary_path": str(summary_path),
                    "highlights": highlights,
                    "checks": check_results,
                    "load_health": assess_load_health(highlights, check_results),
                    "resource_summary": k6_result["resource_summary"],
                    "runtime_docker_stats": k6_result["runtime_samples"],
                }
            )

        log_step("capturing post-traffic container stats")
        docker_stats_after = docker_stats(runtime_container_ids)

        overall_load_health = "green"
        for _k6s in k6_summaries:
            _health = _k6s.get("load_health", {}).get("status", "green")
            if _health == "red":
                overall_load_health = "red"
                break
            if _health == "yellow" and overall_load_health == "green":
                overall_load_health = "yellow"

        compaction_result = None
        verify_result = None
        verification_config = scenario.get("verification", {})
        compact_after_index = verification_config.get(
            "compact_after_traffic_week_index"
        )
        if compact_after_index:
            week_start = dataset_report["weeks"][compact_after_index - 1]["week_start"]
            compaction_begin = time.perf_counter()
            log_step(f"running post-traffic compaction for week {week_start}")
            compaction_stdout = compose_exec(
                project_name,
                BENCHMARK_BACKEND_SERVICE,
                "python",
                "manage.py",
                "compact_weekly_runs",
                week_start,
            ).stdout
            compaction_duration_ms = round(
                (time.perf_counter() - compaction_begin) * 1000, 2
            )
            log_step(
                f"post-traffic compaction finished in {round(compaction_duration_ms / 1000, 2)}s"
            )
            log_step(f"verifying rollups and archives for week {week_start}")
            verify_stdout = compose_exec(
                project_name,
                BENCHMARK_BACKEND_SERVICE,
                "python",
                "manage.py",
                "verify_weekly_rollups",
                week_start,
                "--require-archives",
                "--verify-run-buckets",
            ).stdout
            compaction_result = {
                "week_start": week_start,
                "duration_ms": compaction_duration_ms,
                "stdout": compaction_stdout.strip(),
            }
            verify_result = {"week_start": week_start, "stdout": verify_stdout.strip()}

        post_benchmark_path = scenario_report_dir / "benchmark_post.json"
        post_benchmark_container_path = f"/tmp/{scenario_name}_benchmark_post.json"
        post_benchmark_begin = time.perf_counter()
        log_step("running post-traffic analytics benchmark")
        compose_exec(
            project_name,
            BENCHMARK_BACKEND_SERVICE,
            "python",
            "manage.py",
            "benchmark_teacher_analytics",
            str(first_teacher["teacher_id"]),
            "--iterations",
            benchmark_iterations,
            "--scenario-name",
            f"{scenario_name}_post",
            "--output",
            post_benchmark_container_path,
        )
        log_step(
            f"post-traffic analytics benchmark done in {round((time.perf_counter() - post_benchmark_begin), 2)}s"
        )
        container_cp_from(
            backend_container_id, post_benchmark_container_path, post_benchmark_path
        )
        post_benchmark = load_json(post_benchmark_path)

        scenario_report = {
            "scenario_name": scenario_name,
            "load_health": overall_load_health,
            "scenario_config": scenario,
            "scenario_summary": {
                "compose_project": project_name,
                "scripts": traffic.get("scripts", []),
                "duration": traffic.get("duration", "30s"),
                "base_url": env_map["BASE_URL"],
                "request_host_header": env_map["REQUEST_HOST_HEADER"],
                "benchmark_reference_time": env_map["BENCHMARK_REFERENCE_TIME"],
            },
            "dataset_report": dataset_report,
            "pre_benchmark": pre_benchmark,
            "docker_stats_before": docker_stats_before,
            "k6_summaries": k6_summaries,
            "runtime_docker_stats": all_runtime_samples,
            "resource_summary": summarize_runtime_samples(all_runtime_samples),
            "docker_stats_after": docker_stats_after,
            "compaction_result": compaction_result,
            "verification_result": verify_result,
            "post_benchmark": post_benchmark,
        }
        log_step(f"writing scenario report to {report_output_path}")
        report_output_path.write_text(
            json.dumps(scenario_report, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        log_step("scenario complete")
        print(report_output_path)
    except Exception:
        keep_stack = should_keep_stack_on_failure()
        if keep_stack:
            log_step(f"keeping isolated benchmark stack {project_name} for debugging")
        raise
    finally:
        cleanup_k6_container()
        if not keep_stack:
            log_step(f"tearing down isolated benchmark stack {project_name}")
            compose_down(project_name)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        if exc.output:
            sys.stderr.write(exc.output)
        if getattr(exc, "stderr", None):
            sys.stderr.write(exc.stderr)
        raise
