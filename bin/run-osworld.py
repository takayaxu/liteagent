#!/usr/bin/env python3
"""Run selected OSWorld orders serially from a preserved source/config snapshot."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/single-task-active-thinking.json")
    parser.add_argument("--orders", nargs="+", type=int, required=True)
    parser.add_argument("--result-dir", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
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
    job = (args.result_dir or ROOT.parent / "liteagent-local-runs" / f"{source_mode}-thinking-serial-{stamp}").resolve()
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
    (source / "src/third_party/OSWorld").symlink_to(ROOT / "src/third_party/OSWorld", target_is_directory=True)
    if not seal.source_tree_seal_matches(observed, seal.build_source_tree_seal(snapshot)):
        raise RuntimeError("source changed while preparing snapshot")
    config["tasks"] = [tasks[n] for n in args.orders]
    config["experiment_id"] = job.name
    dump(job / "config.json", config)
    dump(job / "source-seal.json", observed)
    protocol, model = config["protocol"], config["model"]
    command = [str(source / "bin/run-liteagent.sh"), "--config", str(job / "config.json"),
               "--result-dir", str(job / "results"), "--orders", *map(str, args.orders),
               "--base-url", os.environ.get("QWEN_BASE_URL", model["base_urls"][0]),
               "--model", model["requested"], "--reasoning-mode", protocol["reasoning_mode"],
               "--qcow2", "/var/lib/liteagent-shared/Ubuntu.qcow2"]
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
    lock_path = ROOT.parent / "liteagent-reproduction-jobs/v3-repair-vm.lock"
    lock_path.parent.mkdir(exist_ok=True)
    dump(job / "run-status.json", {"status": "waiting_for_lock", "orders": args.orders})
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        dump(job / "run-status.json", {"status": "running", "orders": args.orders})
        with (job / "runner.log").open("x") as log:
            code = subprocess.call(command, cwd=source, env=environment, stdout=log, stderr=subprocess.STDOUT)
    actual = seal.build_source_tree_seal(snapshot)
    integrity = {"source_matches": seal.source_tree_seal_matches(observed, actual),
                 "config_matches": hashlib.sha256((job / "config.json").read_bytes()).hexdigest() == config_digest}
    dump(job / "final-integrity.json", integrity)
    dump(job / "run-status.json", {"status": "runner_exited", "exit_code": code, "integrity": integrity})
    return code if all(integrity.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
