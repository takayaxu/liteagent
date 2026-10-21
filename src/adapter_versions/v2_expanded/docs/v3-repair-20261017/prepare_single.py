#!/usr/bin/env python3
"""Host-only preparation of an isolated local OSWorld single-task attempt."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
SCOPES = (
    "integrations", "scripts", "tests", "deployment", "calc_adapter", "chrome_adapter",
    "gimp_adapter", "impress_adapter", "multi_apps_adapter", "os_adapter",
    "thunderbird_adapter", "vlc_adapter", "vscode_adapter", "writer_adapter", "assets",
)
IGNORED = {"__pycache__", ".pytest_cache", ".ruff_cache"}
PYTHON = "/var/lib/liteagent-shared/python-env/bin/python"
LOCK = "/home/liuxv/liteagent-reproduction-jobs/v3-repair-vm.lock"


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def inventory(root):
    files = []
    active = root / "src/adapter_versions/v2_expanded"
    for scope in SCOPES:
        files.extend(p for p in (active / scope).rglob("*") if p.is_file())
    files.extend(p for p in active.glob("*") if p.is_file())
    files.extend(p for p in (root / "bin").rglob("*") if p.is_file())
    files.append(root / "requirements-liteagent.txt")
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(files))
            if not any(part in IGNORED or part.startswith(".venv") for part in p.relative_to(root).parts)
            and p.suffix != ".pyc"}


def verify(job):
    manifest = json.loads((job / "source-manifest.json").read_text())
    current = inventory(job / "source")
    changed = sorted(p for p in current.keys() | manifest.keys() if current.get(p) != manifest.get(p))
    config_ok = hashlib.sha256((job / "config.json").read_bytes()).hexdigest() == (
        job / "config.sha256").read_text().strip()
    command_ok = hashlib.sha256((job / "command.json").read_bytes()).hexdigest() == (
        job / "command.sha256").read_text().strip()
    return {"status": "ok" if not changed and config_ok and command_ok else "changed",
            "changed_source": changed, "config_ok": config_ok, "command_ok": command_ok,
            "source_files": len(manifest)}


def run(job):
    if (job / "runner.log").exists():
        raise SystemExit("This attempt already started; prepare a new job instead of resuming/overwriting it.")
    before = verify(job)
    dump(job / "initial-source-integrity.json", before)
    if before["status"] != "ok":
        raise SystemExit("Prepared source/config/command changed; prepare a new attempt.")
    env = os.environ.copy()
    metadata = json.loads((job / "preparation.json").read_text())
    env["HF_ENDPOINT"] = metadata["hf_endpoint"]
    # Use only this snapshot's import paths, even when called from another checkout.
    env.pop("PYTHONPATH", None)
    dump(job / "run-status.json", {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()})
    code = None
    try:
        with (job / "runner.log").open("x") as log:
            code = subprocess.call(json.loads((job / "command.json").read_text()),
                                   cwd=job / "source", env=env, stdout=log, stderr=subprocess.STDOUT)
    finally:
        dump(job / "final-source-integrity.json", verify(job))
        dump(job / "run-status.json", {"status": "runner_exited" if code is not None else "interrupted",
             "exit_code": code, "finished_at": datetime.now(timezone.utc).isoformat()})
    return code


def prepare(args):
    workspace = args.workspace.resolve()
    template = json.loads((args.base_config or HERE / "single-task-template.json").read_text())
    tasks = [row for row in template["tasks"] if row["order"] == args.order]
    if len(tasks) != 1:
        raise SystemExit("Choose an Order from the original v3 1..189 list.")
    if min(args.max_steps, args.max_local_steps, args.max_agent_seconds) < 1:
        raise SystemExit("Step and time limits must be positive.")
    template["protocol"]["max_steps"] = args.max_steps
    template["protocol"]["max_local_steps"] = args.max_local_steps
    template["protocol"]["max_agent_seconds"] = args.max_agent_seconds
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.owner):
        raise SystemExit("owner must contain only letters, digits, underscores or hyphens")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    name = f"v3-order{args.order:03d}-{args.owner}-{stamp}"
    job = args.job_root.resolve() / name
    job.mkdir(parents=True, exist_ok=False)
    source = job / "source"
    # Copy the working tree bytes, including uncommitted and new runtime files.
    # Detect concurrent edits during the copy rather than silently mixing versions.
    before = inventory(workspace)
    for relative, digest in before.items():
        original = workspace / relative
        if original.is_symlink():
            raise SystemExit(f"Refuse runtime source symlink: {original}")
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise SystemExit("Source changed while copying; retain this partial job and prepare again.")
    if before != inventory(workspace):
        raise SystemExit("Workspace changed while copying; prepare again after the edit completes.")
    osworld = (workspace / "src/third_party/OSWorld").resolve()
    (source / "src/third_party").mkdir(parents=True)
    (source / "src/third_party/OSWorld").symlink_to(osworld, target_is_directory=True)
    template.update(experiment_id=name, adapter_version="v2_expanded_" + name, tasks=tasks)
    template["sources"]["development_workspace"] = str(source / "src/adapter_versions/v2_expanded")
    dump(job / "config.json", template)
    (job / "config.sha256").write_text(hashlib.sha256((job / "config.json").read_bytes()).hexdigest() + "\n")
    command = [str(source / "bin/run-liteagent.sh"), "--config", str(job / "config.json"),
        "--result-dir", str(job / "results"), "--orders", str(args.order),
        "--qcow2", "/var/lib/liteagent-shared/Ubuntu.qcow2",
        "--base-url", "https://qwen.jinmaoapi.cc.cd/v1", "--model", "Qwen3.5-9B", "--api-key", "EMPTY",
        "--reasoning-mode", "non_thinking", "--max-steps", str(args.max_steps),
        "--max-local-steps", str(args.max_local_steps), "--max-soft-restarts", "1", "--max-no-progress-steps", "8",
        "--max-agent-seconds", str(args.max_agent_seconds), "--max-output-tokens", "8192", "--request-timeout", "240",
        "--model-retries", "3", "--top-k", "7", "--temperature", "0"]
    if args.base_config is None:
        command.extend(["--initial-step-budget", str(min(45, args.max_steps))])
    dump(job / "command.json", command)
    (job / "command.sha256").write_text(hashlib.sha256((job / "command.json").read_bytes()).hexdigest() + "\n")
    dump(job / "source-manifest.json", before)
    with tarfile.open(job / "source-snapshot.tar.gz", "w:gz") as archive:
        for relative in before:
            archive.add(source / relative, arcname=relative)
    for label, cmd in {
        "workspace-status.txt": ["git", "status", "--short"],
        "workspace-diff.patch": ["git", "diff", "--binary", "HEAD"],
        "workspace-head.txt": ["git", "rev-parse", "HEAD"],
        "osworld-commit.txt": ["git", "-C", str(osworld), "rev-parse", "HEAD"],
    }.items():
        result = subprocess.run(cmd, cwd=workspace, capture_output=True)
        (job / label).write_bytes(result.stdout + result.stderr)
    dump(job / "preparation.json", {"prepared_at": datetime.now(timezone.utc).isoformat(),
        "source_workspace": str(workspace), "order": args.order, "owner": args.owner,
        "hf_endpoint": args.hf_endpoint, "osworld_shared_read_only_source": str(osworld),
        "osworld_shared_mutable_cache": str(osworld / "cache"), "vm_started": False})
    shutil.copy2(Path(__file__), job / "host_driver.py")
    (job / "run.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\n"
        "# All cooperating v3 repair dialogs share this host lock; wait before VM startup.\n"
        + "exec flock " + shlex.quote(LOCK) + " " + shlex.quote(PYTHON) + " "
        + shlex.quote(str(job / "host_driver.py")) + " --run-job " + shlex.quote(str(job)) + "\n")
    (job / "run.sh").chmod(0o755)
    print(job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("/home/liuxv/liteagent"))
    parser.add_argument("--job-root", type=Path, default=Path("/home/liuxv/liteagent-reproduction-jobs"))
    parser.add_argument("--order", type=int)
    parser.add_argument("--owner", default="dialog-a")
    parser.add_argument("--hf-endpoint", default="https://hf-mirror.com")
    parser.add_argument("--max-steps", type=int, default=75)
    parser.add_argument("--max-local-steps", type=int, default=25)
    parser.add_argument("--max-agent-seconds", type=int, default=1800)
    parser.add_argument("--base-config", type=Path)
    parser.add_argument("--run-job", type=Path)
    parser.add_argument("--verify-job", type=Path)
    args = parser.parse_args()
    if args.run_job:
        return run(args.run_job.resolve())
    if args.verify_job:
        result = verify(args.verify_job.resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ok" else 1
    if args.order is None:
        parser.error("--order is required for preparation")
    prepare(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
