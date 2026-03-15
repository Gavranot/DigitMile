import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_CONTAINER = "digitmile-backend"
K6_IMAGE = "grafana/k6:0.49.0"


def run_command(command, *, cwd=REPO_ROOT):
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result


def run_manage_py(*args):
    command = ["docker", "exec", BACKEND_CONTAINER, "python", "manage.py", *args]
    return run_command(command)


def docker_cp_from_container(container_path, host_path):
    run_command(
        ["docker", "cp", f"{BACKEND_CONTAINER}:{container_path}", str(host_path)]
    )


def docker_network_for_container(container_name):
    result = run_command(
        [
            "docker",
            "inspect",
            container_name,
            "--format",
            "{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}",
        ]
    )
    return result.stdout.strip()


def docker_stats(container_names):
    result = run_command(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{ json . }}",
            *container_names,
        ]
    )
    stats = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            stats.append(json.loads(line))
    return stats


def run_k6(script_path, summary_path, env_map):
    benchmark_network = docker_network_for_container(BACKEND_CONTAINER)
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        benchmark_network,
        "--add-host",
        "host.docker.internal:host-gateway",
        "-v",
        f"{REPO_ROOT / 'benchmarks'}:/benchmarks",
        "-w",
        "/benchmarks",
        K6_IMAGE,
        "run",
        str(script_path),
        "--summary-export",
        str(summary_path),
    ]
    for key, value in env_map.items():
        command.extend(["-e", f"{key}={value}"])
    return run_command(command)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def json_from_command_output(output_text):
    start = output_text.find("{")
    end = output_text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Command output did not contain JSON")
    return json.loads(output_text[start : end + 1])


def extract_k6_highlights(summary):
    metrics = summary.get("metrics", {})
    highlights = {}
    for metric_name in ["http_req_duration", "http_req_failed", "http_reqs"]:
        metric = metrics.get(metric_name, {})
        highlights[metric_name] = metric.get("values", {})
    return highlights


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
    scenario_report_dir = report_output_path.parent / f"{scenario_name}_artifacts"
    scenario_report_dir.mkdir(parents=True, exist_ok=True)

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
    run_manage_py(*dataset_args)
    dataset_report_path = scenario_report_dir / "dataset.json"
    docker_cp_from_container(dataset_container_path, dataset_report_path)
    dataset_report = load_json(dataset_report_path)
    first_teacher = dataset_report["teachers"][0]

    benchmark_iterations = str(
        scenario.get("verification", {}).get("benchmark_iterations", 5)
    )
    pre_benchmark_path = scenario_report_dir / "benchmark_pre.json"
    pre_benchmark_container_path = f"/tmp/{scenario_name}_benchmark_pre.json"
    run_manage_py(
        "benchmark_teacher_analytics",
        str(first_teacher["teacher_id"]),
        "--iterations",
        benchmark_iterations,
        "--scenario-name",
        f"{scenario_name}_pre",
        "--output",
        pre_benchmark_container_path,
    )
    docker_cp_from_container(pre_benchmark_container_path, pre_benchmark_path)
    pre_benchmark = load_json(pre_benchmark_path)

    k6_summaries = []
    traffic = scenario.get("traffic", {})
    env_map = {
        "BASE_URL": traffic.get("base_url", "http://digitmile-backend:8000"),
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
    }
    docker_stats_before = docker_stats(["digitmile-backend", "digitmile-postgres"])
    for script_name in traffic.get("scripts", []):
        summary_path = scenario_report_dir / f"{Path(script_name).stem}_summary.json"
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
        run_k6(script_path, container_summary_path, container_env_map)
        summary = load_json(summary_path)
        k6_summaries.append(
            {
                "script": script_name,
                "summary_path": str(summary_path),
                "highlights": extract_k6_highlights(summary),
            }
        )
    docker_stats_after = docker_stats(["digitmile-backend", "digitmile-postgres"])

    compaction_result = None
    verify_result = None
    verification_config = scenario.get("verification", {})
    compact_after_index = verification_config.get("compact_after_traffic_week_index")
    if compact_after_index:
        week_start = dataset_report["weeks"][compact_after_index - 1]["week_start"]
        compaction_begin = time.perf_counter()
        compaction_stdout = run_manage_py("compact_weekly_runs", week_start).stdout
        compaction_duration_ms = round(
            (time.perf_counter() - compaction_begin) * 1000, 2
        )
        verify_stdout = run_manage_py(
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
    run_manage_py(
        "benchmark_teacher_analytics",
        str(first_teacher["teacher_id"]),
        "--iterations",
        benchmark_iterations,
        "--scenario-name",
        f"{scenario_name}_post",
        "--output",
        post_benchmark_container_path,
    )
    docker_cp_from_container(post_benchmark_container_path, post_benchmark_path)
    post_benchmark = load_json(post_benchmark_path)

    scenario_report = {
        "scenario_name": scenario_name,
        "scenario_config": scenario,
        "dataset_report": dataset_report,
        "pre_benchmark": pre_benchmark,
        "docker_stats_before": docker_stats_before,
        "k6_summaries": k6_summaries,
        "docker_stats_after": docker_stats_after,
        "compaction_result": compaction_result,
        "verification_result": verify_result,
        "post_benchmark": post_benchmark,
    }
    report_output_path.write_text(
        json.dumps(scenario_report, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(report_output_path)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            sys.stderr.write(exc.stdout)
        if exc.stderr:
            sys.stderr.write(exc.stderr)
        raise
