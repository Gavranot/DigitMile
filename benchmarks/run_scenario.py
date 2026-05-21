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

# Load .env from repo root so the Python process sees variables like
# BENCHMARK_BACKEND_IMAGE that the deploy workflow writes there.
# os.environ takes precedence — .env only fills in missing values.
_dotenv_path = REPO_ROOT / ".env"
if _dotenv_path.is_file():
    with open(_dotenv_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _value = _line.partition("=")
            _key = _key.strip()
            _value = _value.strip().strip("\"'")
            if _key and _key not in os.environ:
                os.environ[_key] = _value

BENCHMARK_COMPOSE_FILE = REPO_ROOT / "benchmarks" / "docker-compose.benchmark.yml"
BENCHMARK_OVERLAYS_DIR = REPO_ROOT / "benchmarks" / "overlays"
BASELINE_WORKTREE_ROOT = REPO_ROOT / ".baseline-worktrees"
BENCHMARK_BACKEND_SERVICE = "benchmark-backend"
BENCHMARK_DB_SERVICE = "benchmark-db"
BENCHMARK_REDIS_SERVICE = "benchmark-redis"
BENCHMARK_FLUSHER_SERVICE = "benchmark-flusher"
K6_IMAGE = "grafana/k6:0.49.0"
K6_CONTAINER_NAME = "digitmile-k6-runner"

# Set by main() once the scenario JSON is parsed. compose_command() reads
# this so every docker compose invocation picks up the overlays.
_ACTIVE_OVERLAY_PATHS: list[Path] = []
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
    cmd = [
        "docker",
        "compose",
        "-f",
        str(BENCHMARK_COMPOSE_FILE),
    ]
    # Scenario-declared overlays merge in declared order, left-to-right.
    for overlay_path in _ACTIVE_OVERLAY_PATHS:
        cmd.extend(["-f", str(overlay_path)])
    # Load .env from repo root so compose picks up BENCHMARK_BACKEND_IMAGE
    # and other variables. Without this, compose only looks in the compose
    # file's directory (benchmarks/), which has no .env.
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        cmd.extend(["--env-file", str(env_file)])
    cmd.extend(["-p", project_name, *args])
    return cmd


def compose_up(project_name):
    log_step(f"starting isolated benchmark stack {project_name}")
    if _is_local_build():
        # Build the backend image once from source. The flusher reuses the
        # same image so we only need to build the backend service.
        log_step("building benchmark backend image from source")
        stream_command(
            compose_command(project_name, "build", BENCHMARK_BACKEND_SERVICE),
            heartbeat_label="docker compose build benchmark-backend",
        )
    stream_command(
        compose_command(
            project_name,
            "up",
            "-d",
            BENCHMARK_DB_SERVICE,
            BENCHMARK_BACKEND_SERVICE,
            BENCHMARK_FLUSHER_SERVICE,
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


def redis_stats(project_name):
    """Query Redis INFO stats + keyspace and return a parsed dict."""
    try:
        stats_result = compose_exec(
            project_name, BENCHMARK_REDIS_SERVICE, "redis-cli", "info", "stats"
        )
        stats = {}
        for line in stats_result.stdout.splitlines():
            if ":" in line and not line.startswith("#"):
                key, _, val = line.strip().partition(":")
                try:
                    stats[key] = int(val)
                except ValueError:
                    try:
                        stats[key] = float(val)
                    except ValueError:
                        stats[key] = val.strip()

        keyspace_result = compose_exec(
            project_name, BENCHMARK_REDIS_SERVICE, "redis-cli", "info", "keyspace"
        )
        keyspace = {}
        for line in keyspace_result.stdout.splitlines():
            if line.startswith("db"):
                db_name, _, db_info = line.strip().partition(":")
                for part in db_info.split(","):
                    k, _, v = part.partition("=")
                    try:
                        keyspace[f"{db_name}_{k.strip()}"] = int(v.strip())
                    except ValueError:
                        keyspace[f"{db_name}_{k.strip()}"] = v.strip()

        return {
            "keyspace_hits": stats.get("keyspace_hits", 0),
            "keyspace_misses": stats.get("keyspace_misses", 0),
            "total_commands_processed": stats.get("total_commands_processed", 0),
            "keyspace": keyspace,
        }
    except Exception as exc:
        return {"error": str(exc)}


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
            "--user",
            "root",
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


def _backend_image_name():
    """Return the image name used by the benchmark backend/flusher services.

    On the server, BENCHMARK_BACKEND_IMAGE is set to the Docker Hub tag
    (e.g. gashmurble/digitmile-backend:prod-latest).
    Locally, it defaults to the locally-built tag.
    """
    return os.getenv("BENCHMARK_BACKEND_IMAGE", "digitmile-benchmark-backend:local")


def _is_local_build():
    """True when we're using a locally-built image (no BENCHMARK_BACKEND_IMAGE set)."""
    return "BENCHMARK_BACKEND_IMAGE" not in os.environ


def ensure_backend_image():
    image = _backend_image_name()
    result = run_command(
        ["docker", "image", "inspect", image],
        check=False,
    )
    if result.returncode == 0:
        if _is_local_build():
            log_step(f"local image {image} found — will rebuild with --build")
        return True

    if _is_local_build():
        log_step(f"local image {image} not found — will be built by compose up --build")
        return True

    # BENCHMARK_BACKEND_IMAGE is set (registry image, including scenario.benchmark_image
    # baselines pushed to a registry for git-less hosts). Try to pull before giving up
    # — this is the path used on the deployment server.
    log_step(f"image {image} not local; attempting docker pull")
    pull = run_command(["docker", "pull", image], check=False)
    if pull.returncode == 0:
        log_step(f"pulled {image}")
        return True

    log_step(
        f"docker pull failed for {image} (exit {pull.returncode}): "
        f"{(pull.stderr or pull.stdout or '').strip()[:300]}"
    )
    return False


def _env_truthy(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return False
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _resolve_overlay_paths(scenario):
    """Validate and resolve compose_overlays entries from the scenario JSON.

    Each entry may be a bare filename (resolved against benchmarks/overlays/)
    or an explicit path. Missing files abort the run before any docker work.

    The BENCHMARK_DISABLE_PGBOUNCER env var, when truthy, force-appends
    no-pgbouncer.yml to every scenario's overlay set so a single export can
    sweep all comparison scenarios without touching their JSON. Duplicates
    are de-duped by filename. Reports for these runs land under a
    no_pgbouncer/ subdirectory so they don't collide with the standard set.
    """
    overlays = scenario.get("compose_overlays") or []
    if not isinstance(overlays, list):
        raise ValueError("scenario.compose_overlays must be a list of overlay filenames")
    resolved: list[Path] = []
    seen_names: set[str] = set()
    for entry in overlays:
        candidate = Path(entry)
        if not candidate.is_absolute():
            candidate = BENCHMARK_OVERLAYS_DIR / candidate
        if not candidate.is_file():
            raise FileNotFoundError(f"compose overlay not found: {candidate}")
        if candidate.name in seen_names:
            continue
        seen_names.add(candidate.name)
        resolved.append(candidate)

    if _env_truthy("BENCHMARK_DISABLE_PGBOUNCER"):
        forced = BENCHMARK_OVERLAYS_DIR / "no-pgbouncer.yml"
        if not forced.is_file():
            raise FileNotFoundError(
                f"BENCHMARK_DISABLE_PGBOUNCER set but {forced} missing"
            )
        if forced.name not in seen_names:
            resolved.append(forced)
            log_step(
                "BENCHMARK_DISABLE_PGBOUNCER=1 → force-appending no-pgbouncer.yml "
                "to this scenario's overlays"
            )

    return resolved


def _sanitize_ref_for_tag(ref):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", ref).strip("-").lower() or "ref"


def _git_resolve_sha(ref):
    result = run_command(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"])
    return result.stdout.strip()


def _ensure_worktree(sha):
    worktree_path = BASELINE_WORKTREE_ROOT / sha[:12]
    if worktree_path.exists():
        return worktree_path
    BASELINE_WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    log_step(f"creating git worktree at {worktree_path} for {sha[:12]}")
    run_command(["git", "worktree", "add", "--detach", str(worktree_path), sha])
    return worktree_path


def _build_baseline_image(ref):
    """Build the backend image from a historical commit and return its tag.

    Worktrees under .baseline-worktrees/ are reused across runs so subsequent
    scenarios using the same baseline skip the checkout cost.
    """
    sha = _git_resolve_sha(ref)
    image_tag = f"digitmile-benchmark-backend:baseline-{_sanitize_ref_for_tag(ref)}-{sha[:12]}"

    inspect = run_command(["docker", "image", "inspect", image_tag], check=False)
    if inspect.returncode == 0:
        log_step(f"reusing baseline image {image_tag}")
        return image_tag

    worktree = _ensure_worktree(sha)
    backend_dir = worktree / "DigitMilePanel"
    dockerfile = backend_dir / "Dockerfile.compose"
    if not dockerfile.is_file():
        raise FileNotFoundError(
            f"baseline ref {ref} ({sha[:12]}) has no DigitMilePanel/Dockerfile.compose — "
            "older commits may use a different image layout"
        )
    log_step(f"building baseline image {image_tag} from {ref} ({sha[:12]})")
    stream_command(
        [
            "docker",
            "build",
            "-t",
            image_tag,
            "-f",
            str(dockerfile),
            str(backend_dir),
        ],
        heartbeat_label=f"docker build baseline {ref}",
    )
    return image_tag


def _apply_baseline_image_ref(scenario):
    """Honour scenario.benchmark_image / benchmark_image_ref.

    Two ways to point the benchmark at a non-tree-HEAD image:

    - scenario["benchmark_image"]: explicit Docker image tag. No git work.
      Compose will pull on first use if the image is not already local.
      Use this on hosts that are not git checkouts (e.g. the thesis
      production server) where we cannot resolve refs locally.

    - scenario["benchmark_image_ref"]: a git ref (tag/branch/SHA). Built
      via `_build_baseline_image` from a worktree. Requires git.

    If both are set, the explicit image wins — set it on hosts without git
    while leaving the ref in the JSON for documentation.
    """
    explicit_image = scenario.get("benchmark_image")
    ref = scenario.get("benchmark_image_ref")

    if explicit_image:
        os.environ["BENCHMARK_BACKEND_IMAGE"] = explicit_image
        log_step(f"benchmark_image={explicit_image} (explicit override; git not consulted)")
        if ref:
            log_step(f"  (scenario also declares benchmark_image_ref={ref}; ignored because explicit image wins)")
        return explicit_image

    if not ref:
        return None

    try:
        image_tag = _build_baseline_image(ref)
    except subprocess.CalledProcessError as exc:
        # Most commonly: `git rev-parse` failed because the host isn't a
        # git checkout. Give a clear remediation hint instead of dumping
        # the raw subprocess traceback.
        raise RuntimeError(
            f"failed to build baseline image for ref {ref!r}: {exc}. "
            "If this host is not a git checkout (e.g. a deployment server), "
            "set scenario.benchmark_image to a prebuilt registry image instead "
            "of relying on benchmark_image_ref. See "
            "docs/decisions/thesis-benchmark-plan.md §5.1."
        ) from exc
    os.environ["BENCHMARK_BACKEND_IMAGE"] = image_tag
    log_step(f"benchmark_image_ref={ref} → using image {image_tag}")
    return image_tag


def _extract_sha_from_image_tag(image):
    """Pull the 12-hex commit SHA suffix from a baseline image tag, if present."""
    match = re.search(r"baseline-.*-([0-9a-f]{12})$", image)
    return match.group(1) if match else None


def verify_backend_image(project_name, scenario):
    """Confirm the running backend container is using the image the scenario asked for.

    Queries the live container, compares against expectations, prints a
    prominent log block, and returns a dict that gets embedded in the
    scenario report under scenario_summary.image_info. Mismatches are fatal
    so a stale image can't silently invalidate a thesis comparison run.
    """
    container_id = compose_service_container_id(project_name, BENCHMARK_BACKEND_SERVICE)
    if not container_id:
        raise RuntimeError("backend container not found — cannot verify image")

    inspect = run_command(
        ["docker", "inspect", container_id, "--format", "{{.Config.Image}}|{{.Image}}"]
    )
    image_name, _, image_digest = inspect.stdout.strip().partition("|")

    requested_ref = scenario.get("benchmark_image_ref")
    explicit_image = scenario.get("benchmark_image")
    expected_image = os.environ.get("BENCHMARK_BACKEND_IMAGE")
    sha = _extract_sha_from_image_tag(image_name)

    # Scenario intent (not just tag shape) determines whether this is a
    # baseline run. Registry-pushed images may not carry the SHA suffix.
    is_baseline = bool(explicit_image or requested_ref)

    info = {
        "image": image_name,
        "image_digest": image_digest,
        "container_id": container_id,
        "mode": "baseline" if is_baseline else "tree-HEAD",
        "requested_benchmark_image_ref": requested_ref,
        "explicit_benchmark_image": explicit_image,
        "resolved_sha": sha,
    }

    if sha:
        try:
            commit = run_command(["git", "show", "-s", "--format=%h %s", sha], check=False)
            if commit.returncode == 0:
                info["commit_subject"] = commit.stdout.strip()
        except Exception:
            pass

    if is_baseline and expected_image and image_name != expected_image:
        raise RuntimeError(
            f"backend image mismatch — scenario asked for image {expected_image} "
            f"but the running container is using {image_name}. "
            "Aborting before any traffic runs."
        )

    banner = "=" * 64
    log_step(banner)
    log_step(f"benchmark backend image: {image_name}")
    log_step(f"  mode: {info['mode']}")
    if explicit_image:
        log_step(f"  explicit benchmark_image: {explicit_image}")
    if requested_ref:
        log_step(f"  benchmark_image_ref: {requested_ref}")
    if sha:
        log_step(f"  resolved SHA: {sha}")
    if info.get("commit_subject"):
        log_step(f"  commit: {info['commit_subject']}")
    if _ACTIVE_OVERLAY_PATHS:
        log_step(f"  overlays: {', '.join(p.name for p in _ACTIVE_OVERLAY_PATHS)}")
    else:
        log_step("  overlays: (none)")
    log_step(banner)

    return info


_PG_SETTINGS_TO_PROBE = (
    "synchronous_commit",
    "shared_buffers",
    "effective_cache_size",
    "work_mem",
    "maintenance_work_mem",
    "wal_buffers",
    "checkpoint_completion_target",
    "random_page_cost",
)

_BACKEND_ENV_TO_PROBE = (
    "DB_HOST",
    "DB_CONN_MAX_AGE",
    "DB_DISABLE_SERVER_SIDE_CURSORS",
    "DJANGO_CACHE_BACKEND",
    "REDIS_URL",
)


def check_disk_safety(storage_walk_cfg, current_db_bytes, label=""):
    """Fail loudly if disk is filling up faster than the scenario tolerates.

    Two ceilings (both optional; either or both can be set in scenario JSON):
      - min_host_free_bytes: aborts if shutil.disk_usage(repo).free < threshold
      - max_pg_db_bytes:     aborts if last pg_database_size() > threshold
    Default thresholds are generous — they catch runaway growth, not normal
    growth.
    """
    import shutil
    min_free = int(storage_walk_cfg.get("min_host_free_bytes", 2 * 1024**3))  # 2 GB
    max_db = storage_walk_cfg.get("max_pg_db_bytes")  # None = no ceiling
    usage = shutil.disk_usage(str(REPO_ROOT))
    free_pct = usage.free / usage.total * 100
    log_step(
        f"  disk: host free {usage.free/1e9:.2f} GB ({free_pct:.1f}%), "
        f"pg db {current_db_bytes/1e9:.2f} GB"
        + (f" / ceiling {int(max_db)/1e9:.2f} GB" if max_db else "")
    )
    if usage.free < min_free:
        raise RuntimeError(
            f"DISK SAFETY ABORT{(' (' + label + ')') if label else ''}: "
            f"host free {usage.free/1e9:.2f} GB below "
            f"min_host_free_bytes={min_free/1e9:.2f} GB. "
            f"Aborting storage walk to leave headroom for OS / logs / WAL."
        )
    if max_db is not None and current_db_bytes > int(max_db):
        raise RuntimeError(
            f"DISK SAFETY ABORT{(' (' + label + ')') if label else ''}: "
            f"pg_database_size {current_db_bytes/1e9:.2f} GB exceeds "
            f"max_pg_db_bytes={int(max_db)/1e9:.2f} GB ceiling. "
            f"This is the NFR-6 failure signal: the configured budget has been "
            f"reached before the year horizon."
        )


def compute_pipeline_integrity(
    pre_counts, post_counts, k6_summaries, redis_queue_residual=0
):
    """
    Sanity-check that k6 traffic actually moved through Redis → flusher → PG.

    The ingest endpoint returns 202 right after LPUSH-ing to the Redis buffer
    — the response says nothing about whether the flusher later succeeded in
    bulk-inserting the rows. Even with 0% http_req_failed, real failure
    modes the HTTP layer can't see:
      - flusher crashes / silently drops items it pops from Redis
      - bulk_create raises and the error path consumes the item anyway
      - ingest 200 dedup path (duplicate run_id) — request counts but no row
      - flusher pointed at a different DB than the one we're inspecting

    The check is non-invasive and never fails the scenario: it emits a
    `pipeline_integrity` section in the report so the operator can see
    whether their throughput numbers reflect real work or just Redis
    enqueues. A healthy ingest-only scenario should have
    `run_delta` ≈ `k6_total_http_reqs - k6_failed_reqs`. Scenarios with
    mixed read+write traffic have `run_delta < k6_total_http_reqs` by
    design — the metric is most useful in ingest-isolated scenarios.

    pre_counts / post_counts: dicts from capture_storage_state().
    Returns a dict suitable for JSON inclusion.
    """
    run_delta = post_counts["run_rows"] - pre_counts["run_rows"]
    turn_delta = post_counts["turnevent_rows"] - pre_counts["turnevent_rows"]
    trigger_delta = (
        post_counts["specialtiletrigger_rows"]
        - pre_counts["specialtiletrigger_rows"]
    )

    k6_total_http_reqs = 0
    k6_failed_reqs_count = 0
    k6_ingest_check_passes = 0
    k6_ingest_check_fails = 0
    for summary in k6_summaries:
        highlights = summary.get("highlights") or {}
        http_reqs = (highlights.get("http_reqs") or {}).get("count", 0) or 0
        http_failed = highlights.get("http_req_failed") or {}
        # http_req_failed is a rate metric: {"rate": float, "passes": int (failed), "fails": int (succeeded)}.
        # The k6 conventions are confusing — `passes` here means the predicate
        # `http_req_failed=true` passed, i.e. the request failed. Sum that.
        failed_count = (
            http_failed.get("passes", 0) or 0
        )
        k6_total_http_reqs += int(http_reqs)
        k6_failed_reqs_count += int(failed_count)
        # Look for any check whose name suggests an ingest-accepted predicate.
        for check_name, counts in (summary.get("checks") or {}).get(
            "by_check", {}
        ).items():
            if "ingest" in check_name.lower() and "accept" in check_name.lower():
                k6_ingest_check_passes += int(counts.get("passes", 0) or 0)
                k6_ingest_check_fails += int(counts.get("fails", 0) or 0)

    expected_runs = max(0, k6_total_http_reqs - k6_failed_reqs_count)
    if expected_runs > 0:
        # Account for any items still sitting in Redis when we sampled — those
        # would have landed in PG eventually, so they're not a leak. Floor at
        # 0 in case the residual estimate overshoots (e.g. duplicate-run-id
        # entries that the flusher will skip).
        adjusted_delta = run_delta + max(0, redis_queue_residual)
        integrity_ratio = round(min(adjusted_delta, expected_runs) / expected_runs, 4)
    else:
        integrity_ratio = None

    # Classify so the operator gets a quick green/yellow/red signal in addition
    # to the raw numbers. Generous bands so mixed-traffic scenarios don't
    # spuriously flag — the operator should read the note before reacting.
    if integrity_ratio is None:
        verdict = "no_ingest_traffic"
    elif integrity_ratio >= 0.95:
        verdict = "green"
    elif integrity_ratio >= 0.50:
        verdict = "yellow"
    else:
        verdict = "red"

    return {
        "pre_traffic_row_counts": {
            "run": pre_counts["run_rows"],
            "turnevent": pre_counts["turnevent_rows"],
            "specialtiletrigger": pre_counts["specialtiletrigger_rows"],
        },
        "post_traffic_row_counts": {
            "run": post_counts["run_rows"],
            "turnevent": post_counts["turnevent_rows"],
            "specialtiletrigger": post_counts["specialtiletrigger_rows"],
        },
        "deltas": {
            "run": run_delta,
            "turnevent": turn_delta,
            "specialtiletrigger": trigger_delta,
        },
        "k6_total_http_reqs": k6_total_http_reqs,
        "k6_failed_reqs": k6_failed_reqs_count,
        "k6_ingest_check_passes": k6_ingest_check_passes,
        "k6_ingest_check_fails": k6_ingest_check_fails,
        "redis_queue_residual": redis_queue_residual,
        "expected_new_runs_if_ingest_only": expected_runs,
        "integrity_ratio": integrity_ratio,
        "verdict": verdict,
        "note": (
            "Compares actual rows landed in PG against k6's HTTP request count. "
            "Most useful for ingest-isolated scenarios. Mixed read+write "
            "scenarios will naturally show ratio < 1.0 since dashboard/replay "
            "traffic does not produce new Run rows. A green verdict on an "
            "ingest-only scenario confirms the pipeline is doing real work."
        ),
    }


def capture_storage_state(project_name):
    """Snapshot pg_database_size and hot-table row counts.

    Used by the storage_walk path (NFR-6). Returns a flat dict so each
    snapshot serializes cleanly into the scenario report.
    """
    db_user = os.getenv("BENCHMARK_DB_USER", "digitmile")
    db_name = os.getenv("BENCHMARK_DB_NAME", "digitmile_benchmark")
    query = (
        "SELECT "
        "pg_database_size(current_database())::bigint, "
        "(SELECT count(*) FROM digitmileapi_turnevent)::bigint, "
        "(SELECT count(*) FROM digitmileapi_specialtiletrigger)::bigint, "
        "(SELECT count(*) FROM digitmileapi_run)::bigint, "
        "pg_total_relation_size('digitmileapi_turnevent')::bigint, "
        "pg_total_relation_size('digitmileapi_specialtiletrigger')::bigint, "
        "pg_total_relation_size('digitmileapi_run')::bigint;"
    )
    result = compose_exec(
        project_name, BENCHMARK_DB_SERVICE,
        "psql", "-U", db_user, "-d", db_name, "-tA", "-c", query,
    )
    parts = [p.strip() for p in result.stdout.strip().split("|")]
    return {
        "db_bytes": int(parts[0]),
        "turnevent_rows": int(parts[1]),
        "specialtiletrigger_rows": int(parts[2]),
        "run_rows": int(parts[3]),
        "turnevent_total_bytes": int(parts[4]),
        "specialtiletrigger_total_bytes": int(parts[5]),
        "run_total_bytes": int(parts[6]),
    }


def verify_stack_state(project_name):
    """Probe the running stack for the settings the overlays target.

    Confirms that overlays *actually* changed runtime state — not just that
    docker compose was given the override file. PG settings come from
    pg_settings (authoritative), backend env vars come from /proc, and the
    Django CACHES backend comes from the live settings module so it includes
    any conditional logic in settings.py.
    """
    state = {}

    # Postgres — pg_settings is the source of truth for what PG actually picked up.
    db_user = os.getenv("BENCHMARK_DB_USER", "digitmile")
    db_name = os.getenv("BENCHMARK_DB_NAME", "digitmile_benchmark")
    pg_names = ",".join(f"'{name}'" for name in _PG_SETTINGS_TO_PROBE)
    pg_query = (
        f"SELECT name || '=' || setting FROM pg_settings "
        f"WHERE name IN ({pg_names});"
    )
    try:
        result = compose_exec(
            project_name, BENCHMARK_DB_SERVICE,
            "psql", "-U", db_user, "-d", db_name, "-tA", "-c", pg_query,
        )
        state["postgres_settings"] = {
            line.split("=", 1)[0]: line.split("=", 1)[1]
            for line in result.stdout.strip().splitlines() if "=" in line
        }
    except subprocess.CalledProcessError as exc:
        state["postgres_settings_error"] = (exc.output or str(exc))[:500]

    # Backend env: shows which DB_HOST / cache backend / pool settings the
    # container actually booted with, which is what settings.py reads.
    try:
        printenv_script = "; ".join(f'echo "{name}=$' + name + '"' for name in _BACKEND_ENV_TO_PROBE)
        result = compose_exec(
            project_name, BENCHMARK_BACKEND_SERVICE,
            "sh", "-c", printenv_script,
        )
        state["backend_env"] = {
            line.split("=", 1)[0]: line.split("=", 1)[1]
            for line in result.stdout.strip().splitlines() if "=" in line
        }
    except subprocess.CalledProcessError as exc:
        state["backend_env_error"] = (exc.output or str(exc))[:500]

    # Django CACHES backend as resolved by settings.py at boot. This catches
    # any drift between the env var and the actual configured backend.
    try:
        result = compose_exec(
            project_name, BENCHMARK_BACKEND_SERVICE,
            "python", "manage.py", "shell", "-c",
            "from django.conf import settings; "
            "print(settings.CACHES['default']['BACKEND'])",
        )
        state["django_cache_backend"] = result.stdout.strip().splitlines()[-1]
    except subprocess.CalledProcessError as exc:
        state["django_cache_backend_error"] = (exc.output or str(exc))[:500]

    # Flusher image — confirms no-flusher.yml swap actually replaced it.
    try:
        flusher_container_id = compose_service_container_id(
            project_name, BENCHMARK_FLUSHER_SERVICE
        )
        if flusher_container_id:
            inspect = run_command([
                "docker", "inspect", flusher_container_id,
                "--format", "{{.Config.Image}}",
            ])
            state["flusher_image"] = inspect.stdout.strip()
    except subprocess.CalledProcessError as exc:
        state["flusher_image_error"] = (exc.output or str(exc))[:500]

    banner = "-" * 64
    log_step(banner)
    log_step("stack state (overlay verification):")
    pg = state.get("postgres_settings") or {}
    for name in _PG_SETTINGS_TO_PROBE:
        if name in pg:
            log_step(f"  pg.{name} = {pg[name]}")
    env = state.get("backend_env") or {}
    for name in _BACKEND_ENV_TO_PROBE:
        if name in env:
            log_step(f"  backend.{name} = {env[name] or '(unset)'}")
    if "django_cache_backend" in state:
        log_step(f"  django CACHES backend = {state['django_cache_backend']}")
    if "flusher_image" in state:
        log_step(f"  flusher image = {state['flusher_image']}")
    log_step(banner)

    return state

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
    # When the user sweeps a comparison set with BENCHMARK_DISABLE_PGBOUNCER,
    # route every report into a no_pgbouncer/ subdirectory so the two sets
    # of numbers stay separate without per-scenario JSON edits.
    if _env_truthy("BENCHMARK_DISABLE_PGBOUNCER"):
        report_output_path = (
            report_output_path.parent / "no_pgbouncer" / report_output_path.name
        )
        log_step(f"report routed under no_pgbouncer/ → {report_output_path}")
    report_output_path.parent.mkdir(parents=True, exist_ok=True)

    scenario_name = scenario.get("name", scenario_path.stem)
    project_name = compose_project_name(scenario_name)
    log_step(f"loaded scenario {scenario_name} from {scenario_path}")
    log_step(f"using isolated compose project {project_name}")
    scenario_report_dir = report_output_path.parent / f"{scenario_name}_artifacts"
    scenario_report_dir.mkdir(parents=True, exist_ok=True)

    # Resolve overlays + baseline image before any docker compose calls so a
    # bad scenario JSON fails fast without leaving a half-started stack.
    _ACTIVE_OVERLAY_PATHS.clear()
    _ACTIVE_OVERLAY_PATHS.extend(_resolve_overlay_paths(scenario))
    if _ACTIVE_OVERLAY_PATHS:
        log_step(
            "applying compose overlays: "
            + ", ".join(p.name for p in _ACTIVE_OVERLAY_PATHS)
        )
    _apply_baseline_image_ref(scenario)

    backend_container_id = None
    db_container_id = None
    redis_container_id = None
    keep_stack = False

    try:
        if not ensure_backend_image():
            return
        compose_up(project_name)
        backend_container_id = wait_for_backend_ready(project_name)
        image_info = verify_backend_image(project_name, scenario)
        stack_state = verify_stack_state(project_name)
        db_container_id = compose_service_container_id(
            project_name, BENCHMARK_DB_SERVICE
        )
        redis_container_id = compose_service_container_id(
            project_name, BENCHMARK_REDIS_SERVICE
        )
        flusher_container_id = compose_service_container_id(
            project_name, BENCHMARK_FLUSHER_SERVICE
        )
        network_name = docker_network_for_container(backend_container_id)
        ensure_k6_container(network_name)

        dataset = scenario["dataset"]
        dataset_container_path = f"/tmp/{scenario_name}_dataset.json"
        # storage_walk needs the verification block read EARLY so we can
        # switch dataset prep into population_only mode before the seeder
        # spends an hour seeding 36 hot weeks all at once.
        _early_verification = scenario.get("verification", {})
        _storage_walk_cfg_early = _early_verification.get("storage_walk")
        _fast_bulk_insert = bool(dataset.get("fast_bulk_insert"))
        if _storage_walk_cfg_early:
            dataset_args = [
                "prepare_benchmark_dataset",
                "--population-only",
                "--teachers", str(dataset["teachers"]),
                "--classrooms-per-teacher", str(dataset["classrooms_per_teacher"]),
                "--students-per-classroom", str(dataset["students_per_classroom"]),
                "--output", dataset_container_path,
                "--clear",
            ]
            # --fast-bulk-insert is irrelevant for --population-only (no runs
            # generated), but pass it through anyway so the flag is consistent.
            if _fast_bulk_insert:
                dataset_args.append("--fast-bulk-insert")
        else:
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
            if _fast_bulk_insert:
                dataset_args.append("--fast-bulk-insert")

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

        verification_config = scenario.get("verification", {})
        storage_walk_cfg = verification_config.get("storage_walk")
        storage_walk_active = bool(storage_walk_cfg)

        benchmark_iterations = str(verification_config.get("benchmark_iterations", 5))
        pre_benchmark = None
        if storage_walk_active:
            log_step(
                "storage_walk mode: skipping pre-traffic analytics benchmark"
            )
        else:
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
        runtime_container_ids = [backend_container_id, db_container_id, redis_container_id]
        if flusher_container_id:
            runtime_container_ids.append(flusher_container_id)

        log_step("capturing baseline container stats")
        docker_stats_before = docker_stats(runtime_container_ids)
        log_step("capturing baseline Redis cache stats")
        redis_stats_before = redis_stats(project_name)
        # Pre-traffic PG row snapshot — paired with the post-drain snapshot
        # below to compute pipeline integrity (do k6's HTTP requests actually
        # turn into PG rows, or are they being lost in the Redis→flusher hop?).
        # storage_walk_active scenarios manage their own per-week pre/post
        # snapshots and don't need this top-level pair.
        pre_traffic_storage_state = (
            None if storage_walk_active else capture_storage_state(project_name)
        )
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

        # Wait for the Redis ingest buffer to drain before collecting final
        # metrics. Generous timeout (up to 60s) so the pipeline integrity
        # check below is reading a settled steady state, not catching the
        # flusher mid-batch — exits early as soon as the queue hits 0.
        log_step("waiting for ingest buffer to drain")
        queue_len = -1
        for _ in range(600):  # up to 60 seconds
            result = compose_exec(
                project_name, BENCHMARK_REDIS_SERVICE,
                "redis-cli", "llen", "ingest_buffer",
            )
            queue_len = int(result.stdout.strip())
            if queue_len == 0:
                break
            time.sleep(0.1)
        log_step(f"ingest buffer drained (queue length: {queue_len})")

        # Post-traffic PG row snapshot (paired with pre_traffic_storage_state)
        # → pipeline integrity check. Captured AFTER the Redis drain so the
        # flusher has had its chance to land everything in PG.
        pipeline_integrity = None
        if pre_traffic_storage_state is not None:
            log_step("capturing post-traffic row counts for pipeline integrity check")
            post_traffic_storage_state = capture_storage_state(project_name)
            pipeline_integrity = compute_pipeline_integrity(
                pre_traffic_storage_state,
                post_traffic_storage_state,
                k6_summaries,
                redis_queue_residual=queue_len,
            )
            ratio = pipeline_integrity["integrity_ratio"]
            ratio_display = "n/a" if ratio is None else f"{ratio:.4f}"
            log_step(
                f"pipeline integrity: {pipeline_integrity['verdict']} "
                f"(ratio={ratio_display}, "
                f"Δrun={pipeline_integrity['deltas']['run']}, "
                f"Δturn={pipeline_integrity['deltas']['turnevent']}, "
                f"k6_http_reqs={pipeline_integrity['k6_total_http_reqs']}, "
                f"k6_failed={pipeline_integrity['k6_failed_reqs']})"
            )

        log_step("capturing post-traffic container stats")
        docker_stats_after = docker_stats(runtime_container_ids)
        log_step("capturing post-traffic Redis cache stats")
        redis_stats_after = redis_stats(project_name)
        hits = redis_stats_after.get("keyspace_hits", 0) - redis_stats_before.get("keyspace_hits", 0)
        misses = redis_stats_after.get("keyspace_misses", 0) - redis_stats_before.get("keyspace_misses", 0)
        total = hits + misses
        hit_rate = round(hits / total * 100, 1) if total > 0 else 0
        redis_cache_summary = {
            "hits": hits,
            "misses": misses,
            "total_lookups": total,
            "hit_rate_pct": hit_rate,
            "keys_stored": redis_stats_after.get("keyspace", {}).get("db1_keys", 0),
        }
        log_step(
            f"Redis cache: {hits} hits / {misses} misses / {total} total lookups"
            f" — hit rate {hit_rate}%"
            f" — {redis_cache_summary['keys_stored']} keys stored"
        )

        overall_load_health = "green"
        for _k6s in k6_summaries:
            _health = _k6s.get("load_health", {}).get("status", "green")
            if _health == "red":
                overall_load_health = "red"
                break
            if _health == "yellow" and overall_load_health == "green":
                overall_load_health = "yellow"

        compaction_result = None
        storage_trajectory = None
        storage_trajectory_summary = None
        compact_after_index = verification_config.get(
            "compact_after_traffic_week_index"
        )
        if storage_walk_active:
            total_weeks = int(storage_walk_cfg.get("total_weeks", 36))
            compact_through = int(
                storage_walk_cfg.get("compact_through_week_index", total_weeks - 1)
            )
            anchor_str = dataset.get("anchor_week_start")
            if not anchor_str:
                raise RuntimeError(
                    "storage_walk requires dataset.anchor_week_start in scenario JSON"
                )
            from datetime import date, datetime as _dt, timedelta as _td
            anchor_date = _dt.strptime(anchor_str, "%Y-%m-%d").date()
            week_dates = [
                (anchor_date + _td(weeks=i - 1)).isoformat()
                for i in range(1, total_weeks + 1)
            ]
            runs_per_student = int(dataset["runs_per_student_per_week"])
            avg_turns = int(dataset["avg_turns_per_run"])

            log_step(
                f"storage walk: {total_weeks} weeks, compacting weeks 1..{compact_through} "
                f"(week {total_weeks} stays hot to mirror production 'current week')"
            )

            baseline = capture_storage_state(project_name)
            log_step(
                f"  baseline (population seeded, no runs): "
                f"db={baseline['db_bytes']/1e6:.1f} MB, "
                f"runs={baseline['run_rows']}, "
                f"students seeded ok"
            )
            check_disk_safety(storage_walk_cfg, baseline["db_bytes"], label="baseline")
            storage_trajectory = [
                {
                    "step": 0,
                    "week_index": 0,
                    "label": "baseline_post_population_seed",
                    "snapshot": baseline,
                }
            ]

            for week_index in range(1, total_weeks + 1):
                week_start = week_dates[week_index - 1]
                will_compact = week_index <= compact_through

                # --- SEED one week of runs ---
                seed_begin = time.perf_counter()
                log_step(
                    f"  [{week_index}/{total_weeks}] seeding week {week_start}"
                    + ("" if will_compact else " (final hot week, will not compact)")
                )
                append_args = [
                    "prepare_benchmark_dataset",
                    "--append-week-start", week_start,
                    "--runs-per-student-per-week", str(runs_per_student),
                    "--avg-turns-per-run", str(avg_turns),
                    "--card-mix-profile", dataset.get("card_mix_profile", "balanced"),
                    "--bag-level-ratio", str(dataset.get("bag_level_ratio", 0.35)),
                    "--seed", str(20260312 + week_index),
                ]
                if _fast_bulk_insert:
                    append_args.append("--fast-bulk-insert")
                compose_exec_stream(
                    project_name,
                    BENCHMARK_BACKEND_SERVICE,
                    "python",
                    "manage.py",
                    *append_args,
                )
                seed_duration_ms = round(
                    (time.perf_counter() - seed_begin) * 1000, 2
                )
                post_seed = capture_storage_state(project_name)
                check_disk_safety(
                    storage_walk_cfg,
                    post_seed["db_bytes"],
                    label=f"week {week_index} post-seed",
                )
                log_step(
                    f"     seed: {seed_duration_ms/1000:.1f}s, "
                    f"db {baseline['db_bytes']/1e6:.1f} → "
                    f"{post_seed['db_bytes']/1e6:.1f} MB "
                    f"(+{(post_seed['db_bytes']-baseline['db_bytes'])/1e6:.1f} MB)"
                )

                # --- COMPACT this week (except the final hot week) ---
                compact_duration_ms = None
                compact_stdout = None
                post_compact = post_seed
                if will_compact:
                    compact_begin = time.perf_counter()
                    compact_args = [
                        "python",
                        "manage.py",
                        "compact_weekly_runs",
                        week_start,
                    ]
                    # Per-teacher mode bounds per-call memory and PG insert
                    # pressure to ~one teacher's slice (~100 students). At
                    # national-medium scale a monolithic call OOM-kills PG on
                    # the 3.8 GiB host; per-teacher iteration is the only
                    # invocation pattern that fits.
                    if storage_walk_cfg.get("compaction_per_teacher"):
                        compact_args.append("--per-teacher")
                        # Optional parallel-worker count. Default 1
                        # (sequential) preserves NFR-6 canonical behaviour;
                        # set higher in the scenario JSON to shorten weekly
                        # compaction wall time at the cost of more PG
                        # connections in-flight. DIGITMILE_COMPACTION_MAX_WORKERS
                        # env var overrides the scenario JSON for per-run
                        # tuning without editing config.
                        max_workers = int(
                            os.environ.get(
                                "DIGITMILE_COMPACTION_MAX_WORKERS",
                                storage_walk_cfg.get("compaction_max_workers", 1),
                            )
                        )
                        if max_workers > 1:
                            compact_args.extend(
                                ["--max-workers", str(max_workers)]
                            )
                    # Stream so per-teacher progress lines show in real time
                    # rather than buffering for the whole 30–60 min run.
                    # stream_command returns the captured combined output,
                    # which we still want for the trajectory report.
                    compact_stdout = compose_exec_stream(
                        project_name,
                        BENCHMARK_BACKEND_SERVICE,
                        *compact_args,
                    )
                    compact_duration_ms = round(
                        (time.perf_counter() - compact_begin) * 1000, 2
                    )
                    post_compact = capture_storage_state(project_name)
                    reclaimed = post_seed["db_bytes"] - post_compact["db_bytes"]
                    log_step(
                        f"     compact: {compact_duration_ms/1000:.1f}s, "
                        f"reclaimed {reclaimed/1e6:+.1f} MB "
                        f"(db {post_seed['db_bytes']/1e6:.1f} → "
                        f"{post_compact['db_bytes']/1e6:.1f} MB)"
                    )
                    check_disk_safety(
                        storage_walk_cfg,
                        post_compact["db_bytes"],
                        label=f"week {week_index} post-compact",
                    )

                storage_trajectory.append(
                    {
                        "step": week_index,
                        "week_index": week_index,
                        "week_start": week_start,
                        "post_seed": post_seed,
                        "post_compact": post_compact,
                        "compacted": will_compact,
                        "seed_duration_ms": seed_duration_ms,
                        "compact_duration_ms": compact_duration_ms,
                        "reclaimed_bytes": (
                            post_seed["db_bytes"] - post_compact["db_bytes"]
                            if will_compact else 0
                        ),
                        "compaction_stdout": (
                            compact_stdout.strip() if compact_stdout else None
                        ),
                    }
                )

            final_snapshot = storage_trajectory[-1].get("post_compact") or storage_trajectory[-1].get("post_seed")
            total_reclaimed = sum(
                s.get("reclaimed_bytes", 0) for s in storage_trajectory[1:]
            )
            compact_durations = [
                s["compact_duration_ms"] for s in storage_trajectory[1:]
                if s.get("compact_duration_ms") is not None
            ]
            seed_durations = [
                s["seed_duration_ms"] for s in storage_trajectory[1:]
                if s.get("seed_duration_ms") is not None
            ]
            storage_trajectory_summary = {
                "weeks_seeded": total_weeks,
                "weeks_compacted": compact_through,
                "baseline_db_bytes": baseline["db_bytes"],
                "final_db_bytes": final_snapshot["db_bytes"],
                "net_growth_bytes": final_snapshot["db_bytes"] - baseline["db_bytes"],
                "total_reclaimed_bytes": total_reclaimed,
                "avg_seed_duration_ms": (
                    round(sum(seed_durations) / len(seed_durations), 2)
                    if seed_durations else 0
                ),
                "avg_compaction_duration_ms": (
                    round(sum(compact_durations) / len(compact_durations), 2)
                    if compact_durations else 0
                ),
                "max_compaction_duration_ms": (
                    round(max(compact_durations), 2) if compact_durations else 0
                ),
            }
            log_step("-" * 64)
            log_step(
                f"storage walk complete: baseline {baseline['db_bytes']/1e6:.1f} MB → "
                f"final {final_snapshot['db_bytes']/1e6:.1f} MB "
                f"(net {(final_snapshot['db_bytes']-baseline['db_bytes'])/1e6:+.1f} MB, "
                f"total reclaimed {total_reclaimed/1e6:.1f} MB)"
            )
        elif compact_after_index:
            week_start = dataset_report["weeks"][compact_after_index - 1]["week_start"]
            compaction_begin = time.perf_counter()
            log_step(f"running post-traffic compaction for week {week_start}")
            # compact_weekly_runs runs verify_weekly_rollups internally before
            # deleting the raw TurnEvent/SpecialTileTrigger rows (see
            # digitmileapi/management/commands/compact_weekly_runs.py). If
            # compaction returns 0 the rollups already matched raw at the
            # pre-delete checkpoint. Re-running verify_weekly_rollups here
            # would be unsound: raw rows are gone and every comparison
            # would report raw=0 / rollup=<n>.
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
            compaction_result = {
                "week_start": week_start,
                "duration_ms": compaction_duration_ms,
                "stdout": compaction_stdout.strip(),
            }

        post_benchmark = None
        if storage_walk_active:
            log_step(
                "storage_walk mode: skipping post-traffic analytics benchmark"
            )
        else:
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
                "image_info": image_info,
                "compose_overlays": [str(p) for p in _ACTIVE_OVERLAY_PATHS],
                "stack_state": stack_state,
            },
            "dataset_report": dataset_report,
            "pre_benchmark": pre_benchmark,
            "docker_stats_before": docker_stats_before,
            "k6_summaries": k6_summaries,
            "runtime_docker_stats": all_runtime_samples,
            "resource_summary": summarize_runtime_samples(all_runtime_samples),
            "docker_stats_after": docker_stats_after,
            "redis_stats_before": redis_stats_before,
            "redis_stats_after": redis_stats_after,
            "redis_cache_summary": redis_cache_summary,
            "pipeline_integrity": pipeline_integrity,
            "compaction_result": compaction_result,
            "storage_trajectory": storage_trajectory,
            "storage_trajectory_summary": storage_trajectory_summary,
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
