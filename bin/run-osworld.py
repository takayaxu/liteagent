#!/usr/bin/env python3
"""Run selected orders in an isolated snapshot/guest; allow parallel repair dialogs."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid
from contextlib import contextmanager

from model_env import load_model_environment
from repair_resources import RepairResources

ROOT = Path(__file__).resolve().parents[1]


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def prepare_osworld(original, destination, tasks):
    """Copy evaluator/setup source and only selected task caches into this run."""
    before = osworld_digest(original)
    shutil.copytree(original, destination, ignore=shutil.ignore_patterns(
        ".git", ".conda", ".venv*", "cache", "docker_vm_data", "__pycache__", "*.pyc",
        ".pytest_cache", ".ruff_cache", "logs", "results", "recordings",
    ))
    for task in tasks:
        cache = original / "cache" / task["task_id"]
        if cache.is_dir():
            shutil.copytree(cache, destination / "cache" / task["task_id"])
    copied = osworld_digest(destination)
    if copied != before or osworld_digest(original) != before:
        raise RuntimeError("OSWorld source changed while preparing isolated snapshot")
    return copied


def osworld_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {"cache", "docker_vm_data", ".git", ".conda", "__pycache__",
                        "logs", "results", "recordings", ".pytest_cache", ".ruff_cache"}
               or part.startswith(".venv")
               for part in relative.parts) or path.suffix == ".pyc" or not path.is_file():
            continue
        digest.update(relative.as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


@contextmanager
def legacy_resource_lock(on_wait, exclusive=False):
    # SH allows isolated dialogs to overlap. Old EX holders finish first.
    path = Path.home() / "liteagent-reproduction-jobs/v3-repair-vm.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        while True:
            try:
                operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(handle, operation | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                on_wait("legacy_exclusive_run")
                time.sleep(1)
        yield path, handle.fileno()


def run_owned(command, *, source, environment, log, inherited_fds, owner):
    process = subprocess.Popen(command, cwd=source, env=environment, stdout=log,
                               stderr=subprocess.STDOUT, start_new_session=True,
                               pass_fds=inherited_fds)
    try:
        return process.wait()
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass  # The child may exit between poll and killpg; still clean owned guests.
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        # Catch interrupted deployment/teardown leftovers; never touch other owners.
        listed = subprocess.run(
            ["docker", "ps", "-aq", "--filter", f"label=openapa.run_owner={owner}"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if listed.returncode:
            raise RuntimeError("cannot verify owned guest cleanup: " + listed.stderr[-2000:])
        for container in listed.stdout.split():
            subprocess.run(["docker", "rm", "-fv", container], timeout=90, check=True,
                           stdout=log, stderr=subprocess.STDOUT)


def _terminate(signum, _frame):
    raise SystemExit(128 + signum)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/single-task-active-thinking.json")
    parser.add_argument("--orders", nargs="+", type=int, required=True)
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--exclusive", action="store_true",
                        help="Reserve all repair slots and the legacy exclusive lock.")
    parser.add_argument("--qcow2", type=Path,
                        default=Path("/var/lib/liteagent-shared/Ubuntu.qcow2"))
    args = parser.parse_args()
    args.qcow2 = args.qcow2.expanduser().resolve()
    if not args.qcow2.is_file():
        parser.error("--qcow2 must name an existing read-only guest base image")
    load_model_environment()
    config = json.loads(args.config.read_text())
    model = config["model"]
    base_url = os.environ.get("QWEN_BASE_URL") or next(iter(model.get("base_urls", [])), None)
    if not base_url:
        parser.error("set QWEN_BASE_URL or configure ~/.config/liteagent/model.env")
    model["base_urls"] = [base_url]
    model["requested"] = os.environ.get("QWEN_MODEL", model["requested"])
    tasks = {task["order"]: task for task in config["tasks"]}
    if len(set(args.orders)) != len(args.orders) or any(n not in tasks for n in args.orders):
        parser.error("orders must be unique and present in the config")
    active = ROOT / "src/adapter_versions/v2_expanded"
    spec = importlib.util.spec_from_file_location("source_seal", active / "scripts/condition_seal.py")
    seal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seal)
    observed = seal.build_source_tree_seal(active)
    source_mode = config["sources"].get("source_mode", "frozen")
    if source_mode not in {"active", "frozen"}:
        parser.error("sources.source_mode must be active or frozen")
    if source_mode == "active":
        config["sources"]["baseline_source_sha256"] = observed["sha256"]
        config["sources"]["baseline_source_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        config["sources"]["working_tree_dirty"] = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    elif observed["sha256"] != config["sources"]["baseline_source_sha256"]:
        parser.error("active runtime differs from the configured frozen source")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    job = (args.result_dir or ROOT.parent / "liteagent-local-runs" / f"{source_mode}-thinking-repair-{stamp}").resolve()
    job.mkdir(parents=True, exist_ok=False)
    source = job / "source"
    snapshot = source / "src/adapter_versions/v2_expanded"
    snapshot.mkdir(parents=True)
    for scope in (*seal.SOURCE_SCOPE_ROOTS, "assets"):
        if (active / scope).exists():
            shutil.copytree(active / scope, snapshot / scope,
                            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache", "*.pyc"))
    for path in active.iterdir():
        if path.is_file():
            shutil.copy2(path, snapshot / path.name)
    shutil.copytree(ROOT / "bin", source / "bin", ignore=shutil.ignore_patterns("__pycache__"))
    (source / "src/third_party").mkdir()
    selected_tasks = [tasks[n] for n in args.orders]
    osworld = source / "src/third_party/OSWorld"
    osworld_sha256 = prepare_osworld(ROOT / "src/third_party/OSWorld", osworld, selected_tasks)
    if not seal.source_tree_seal_matches(observed, seal.build_source_tree_seal(snapshot)):
        raise RuntimeError("source changed while preparing snapshot")
    config["tasks"] = selected_tasks
    config["experiment_id"] = job.name
    dump(job / "config.json", config)
    dump(job / "source-seal.json", observed)
    protocol, model = config["protocol"], config["model"]
    command = [str(source / "bin/run-liteagent.sh"), "--config", str(job / "config.json"),
               "--result-dir", str(job / "results"), "--orders", *map(str, args.orders),
               "--base-url", model["base_urls"][0],
               "--model", model["requested"], "--reasoning-mode", protocol["reasoning_mode"],
               "--qcow2", str(args.qcow2)]
    for name in ("max_steps", "initial_step_budget", "max_local_steps", "max_soft_restarts",
                 "max_no_progress_steps", "max_agent_seconds", "max_output_tokens", "top_k",
                 "temperature", "request_timeout", "model_retries", "initial_settle_seconds",
                 "action_settle_seconds", "evaluator_settle_seconds", "evaluator_file_fetch_attempts",
                 "evaluator_file_fetch_delay_seconds"):
        command.extend(["--" + name.replace("_", "-"), str(protocol[name])])
    if protocol["thinking"]:
        command.append("--thinking")
    dump(job / "command.json", command)
    config_digest = hashlib.sha256((job / "config.json").read_bytes()).hexdigest()
    print(job, flush=True)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    owner = "lite-repair-" + uuid.uuid4().hex
    environment["OPENAPA_RUN_OWNER"] = owner
    environment["LITE_AGENT_RUN_OWNER"] = owner
    metadata = {"owner": owner, "orders": args.orders, "result_dir": str(job),
                "source_commit": config["sources"].get("baseline_source_commit"),
                "source_sha256": observed["sha256"], "qcow2": str(args.qcow2),
                "guest_isolation": "fresh_docker_container_per_task",
                "osworld_snapshot_sha256": osworld_sha256}
    dump(job / "resource-request.json", metadata)
    code = None
    previous_handlers = {sig: signal.signal(sig, _terminate)
                         for sig in (signal.SIGTERM, signal.SIGINT)}
    last_reason = None

    def waiting(reason):
        nonlocal last_reason
        if reason != last_reason:
            dump(job / "run-status.json", {"status": "waiting_for_resources",
                                           "reason": reason, "orders": args.orders,
                                           "owner": owner})
            print(f"waiting for resources: {reason}", flush=True)
            last_reason = reason

    try:
        with legacy_resource_lock(waiting, args.exclusive) as (legacy_path, legacy_fd):
            pool = RepairResources()
            with pool.acquire(task_ids=[task["task_id"] for task in selected_tasks],
                              metadata=metadata, exclusive=args.exclusive,
                              on_wait=waiting) as (receipt, lease_fds):
                receipt["legacy_lock"] = str(legacy_path)
                receipt["legacy_lock_mode"] = "exclusive" if args.exclusive else "shared"
                dump(job / "resource-lease.json", receipt)
                dump(job / "run-status.json", {"status": "running", "orders": args.orders,
                                               "owner": owner})
                with (job / "runner.log").open("x") as log:
                    code = run_owned(command, source=source, environment=environment, log=log,
                                     inherited_fds=(*lease_fds, legacy_fd), owner=owner)
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        actual = seal.build_source_tree_seal(snapshot)
        integrity = {"source_matches": seal.source_tree_seal_matches(observed, actual),
                     "config_matches": hashlib.sha256((job / "config.json").read_bytes()).hexdigest() == config_digest,
                     "osworld_matches": osworld_digest(osworld) == osworld_sha256}
        dump(job / "final-integrity.json", integrity)
        dump(job / "run-status.json", {"status": "runner_exited" if code is not None else "interrupted_or_failed",
                                       "exit_code": code, "integrity": integrity, "owner": owner})
    return code if all(integrity.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
