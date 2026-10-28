"""Exercise real process locks and the public snapshot/runner entrypoint."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from repair_resources import RepairResources  # noqa: E402


def wait_until(predicate, processes=(), timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        for process in processes:
            if process.poll() is not None:
                out, err = process.communicate()
                pytest.fail(f"process exited early: {process.returncode}: {out} {err}")
        time.sleep(.02)
    pytest.fail("timed out waiting for process evidence")


@pytest.fixture
def children():
    processes = []
    yield processes
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def worker(pool, task, release, ready, children, exclusive=False):
    code = '''
import json,sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from repair_resources import RepairResources
with RepairResources(sys.argv[2]).acquire(task_ids=[sys.argv[3]], metadata={'owner':sys.argv[3]}, exclusive=sys.argv[6]=='True') as (receipt, fds):
    Path(sys.argv[5]).write_text(json.dumps(receipt))
    while not Path(sys.argv[4]).exists(): time.sleep(.02)
'''
    process = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "bin"), str(pool), task,
                                str(release), str(ready), str(exclusive)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    children.append(process)
    return process


def test_distinct_processes_overlap_same_task_waits_and_capacity_is_enforced(tmp_path, children):
    pool = RepairResources(tmp_path / "pool")
    pool.configure(2)
    stop1, stop2 = tmp_path / "stop1", tmp_path / "stop2"
    ready1, ready2 = tmp_path / "ready1", tmp_path / "ready2"
    first = worker(pool.root, "task-a", stop1, ready1, children)
    second = worker(pool.root, "task-b", stop2, ready2, children)
    wait_until(lambda: ready1.exists() and ready2.exists(), [first, second])
    assert pool.status()["occupied_slots"] == 2
    third_ready = tmp_path / "third"
    third = worker(pool.root, "task-c", tmp_path / "stop3", third_ready, children)
    duplicate_ready = tmp_path / "duplicate"
    duplicate = worker(pool.root, "task-a", tmp_path / "stop4", duplicate_ready, children)
    time.sleep(.15)
    assert not third_ready.exists() and not duplicate_ready.exists()
    with pytest.raises(RuntimeError, match="while a run holds"):
        pool.configure(1)
    stop2.touch()
    second.wait(timeout=5)
    wait_until(third_ready.exists, [third])
    assert not duplicate_ready.exists()  # A free slot cannot override the task claim.
    stop1.touch()
    first.wait(timeout=5)
    wait_until(duplicate_ready.exists, [duplicate])


def test_killed_lease_owner_releases_slots_and_stale_receipts_are_not_active(tmp_path, children):
    pool = RepairResources(tmp_path / "pool")
    ready = tmp_path / "ready"
    process = worker(pool.root, "one", tmp_path / "stop", ready, children)
    wait_until(ready.exists, [process])
    process.kill()
    process.wait()
    assert pool.status()["occupied_slots"] == 0
    with pool.acquire(task_ids=["one"], metadata={}) as (receipt, _):
        assert receipt["pool_capacity"] == 5


def test_exclusive_lease_uses_all_slots_and_task_conflict_does_not_reserve_slot(tmp_path):
    pool = RepairResources(tmp_path / "pool")
    with pool.acquire(task_ids=["one"], metadata={}, exclusive=True):
        assert pool.status()["occupied_slots"] == 5
        with pytest.raises(RuntimeError, match="exclusive"):
            pool.configure(6)
        with pytest.raises(TimeoutError):
            with pool.acquire(task_ids=["two"], metadata={}, timeout=0):
                pytest.fail("exclusive lease was bypassed")
    with pool.acquire(task_ids=["one"], metadata={}):
        with pytest.raises(TimeoutError, match="same_task"):
            with pool.acquire(task_ids=["one", "other"], metadata={}, timeout=0):
                pytest.fail("same task was not protected")
        assert pool.status()["occupied_slots"] == 1
        with pool.acquire(task_ids=["other"], metadata={}, timeout=0):
            pass


def test_online_expansion_preserves_active_leases_and_admits_waiting_run(tmp_path, children):
    pool = RepairResources(tmp_path / "pool")
    pool.configure(1)
    ready1, ready2 = tmp_path / "ready1", tmp_path / "ready2"
    first = worker(pool.root, "first", tmp_path / "stop1", ready1, children)
    wait_until(ready1.exists, [first])
    receipt = ready1.read_bytes()
    second = worker(pool.root, "second", tmp_path / "stop2", ready2, children)
    time.sleep(.15)
    assert not ready2.exists()
    status = pool.configure(5)
    assert status["capacity"] == 5
    wait_until(ready2.exists, [first, second])
    assert first.poll() is None
    assert ready1.read_bytes() == receipt
    assert pool.status()["occupied_slots"] == 2
    assert json.loads(ready2.read_text())["pool_capacity"] == 5
    with pytest.raises(RuntimeError, match="while a run holds"):
        pool.configure(1)
    assert pool.status()["capacity"] == 5


def test_online_expansion_refuses_unverifiable_active_lease(tmp_path):
    pool = RepairResources(tmp_path / "pool")
    pool.configure(1)
    with pool.acquire(task_ids=["one"], metadata={}):
        (pool.root / "slot-0.json").write_text("invalid metadata")
        with pytest.raises(RuntimeError, match="unknown active lease"):
            pool.configure(5)
        assert pool.status()["capacity"] == 1


def test_inherited_lease_stays_held_if_wrapper_is_killed(tmp_path, children):
    pool = RepairResources(tmp_path / "pool")
    ready = tmp_path / "child-pid"
    stop = tmp_path / "stop"
    code = '''
import subprocess,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from repair_resources import RepairResources
with RepairResources(sys.argv[2]).acquire(task_ids=['task'],metadata={}) as (_,fds):
    child=subprocess.Popen([sys.executable,'-c',"import sys,time; from pathlib import Path; p=Path(sys.argv[1]); exec('while not p.exists(): time.sleep(.02)')",sys.argv[3]],pass_fds=fds)
    Path(sys.argv[4]).write_text(str(child.pid))
    child.wait()
'''
    process = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "bin"), str(pool.root), str(stop), str(ready)])
    children.append(process)
    wait_until(ready.exists, [process])
    try:
        process.kill()
        process.wait()
        assert pool.status()["occupied_slots"] == 1
    finally:
        stop.touch()
    wait_until(lambda: pool.status()["occupied_slots"] == 0)


def _fixture_project(root):
    root.mkdir()
    (root / "bin").mkdir()
    for name in ("run-osworld.py", "model_env.py", "repair_resources.py"):
        (root / "bin" / name).write_bytes((ROOT / "bin" / name).read_bytes())
    v2 = root / "src/adapter_versions/v2_expanded"
    (v2 / "scripts").mkdir(parents=True)
    (v2 / "scripts/condition_seal.py").write_bytes(
        (ROOT / "src/adapter_versions/v2_expanded/scripts/condition_seal.py").read_bytes())
    (v2 / "integrations").mkdir()
    (v2 / "integrations/fact.py").write_text("VALUE=1\n")
    native = root / "src/third_party/OSWorld"
    (native / "cache/task").mkdir(parents=True)
    (native / "cache/task/source").write_text("immutable input")
    (native / "cache/other").mkdir()
    (native / "cache/other/source").write_text("immutable input")
    (native / "evaluator.py").write_text("pinned evaluator")
    (root / "configs").mkdir()
    config = json.loads((ROOT / "configs/single-task-active-thinking.json").read_text())
    config["tasks"] = [{"order": 1, "task_id": "task", "domain": "synthetic"},
                       {"order": 2, "task_id": "other", "domain": "synthetic"}]
    (root / "configs/single-task-active-thinking.json").write_text(json.dumps(config))
    for args in (["init", "-q"], ["add", "."],
                 ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    runner = root / "bin/run-liteagent.sh"
    runner.write_text('''#!/usr/bin/env python3
import json,os,sys,time
from pathlib import Path
job=Path(sys.argv[sys.argv.index('--result-dir')+1]).parent
(job/'synthetic-started').write_text(json.dumps({'owner':os.environ['OPENAPA_RUN_OWNER'],'started':time.time()}))
while not (job/'synthetic-release').exists():time.sleep(.02)
task='task' if sys.argv[sys.argv.index('--orders')+1]=='1' else 'other'
(job/'source/src/third_party/OSWorld/cache'/task/'source').write_text('run local change')
''')
    runner.chmod(0o755)
    return root


def test_public_entrypoint_parallel_snapshots_and_legacy_compatibility(tmp_path, children):
    first_root = _fixture_project(tmp_path / "project1")
    second_root = _fixture_project(tmp_path / "project2")
    home = tmp_path / "home"
    home.mkdir()
    qcow = tmp_path / "base.qcow2"
    qcow.write_bytes(b"synthetic immutable base")
    executables = tmp_path / "executables"
    executables.mkdir()
    docker = executables / "docker"
    docker.write_text('#!/bin/sh\nexit 0\n')
    docker.chmod(0o755)
    environment = {**os.environ, "HOME": str(home), "QWEN_BASE_URL": "http://synthetic/v1",
                   "PATH": str(executables)+os.pathsep+os.environ["PATH"]}
    jobs = [tmp_path / "run1", tmp_path / "run2"]
    legacy = home / "liteagent-reproduction-jobs/v3-repair-vm.lock"
    legacy.parent.mkdir()
    import fcntl
    with legacy.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for index, root in enumerate([first_root, second_root]):
            command = [sys.executable, str(root / "bin/run-osworld.py"), "--orders", str(index+1),
                       "--result-dir", str(jobs[index]), "--qcow2", str(qcow)]
            children.append(subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, text=True))
        wait_until(lambda: all((job / "run-status.json").exists() for job in jobs), children)
        for job in jobs:
            assert json.loads((job / "run-status.json").read_text())["reason"] == "legacy_exclusive_run"
            assert not (job / "synthetic-started").exists()
    wait_until(lambda: all((job / "synthetic-started").exists() for job in jobs), children)
    receipts = [json.loads((job / "resource-lease.json").read_text()) for job in jobs]
    assert receipts[0]["owner"] != receipts[1]["owner"]
    assert receipts[0]["slots"] != receipts[1]["slots"]
    assert receipts[0]["resource_directory"] == receipts[1]["resource_directory"]
    for job in jobs:
        assert not (job / "source/src/third_party/OSWorld").is_symlink()
        (job / "synthetic-release").touch()
    for process in children:
        out, err = process.communicate(timeout=15)
        assert process.returncode == 0, (out, err)
    for root, job in zip([first_root, second_root], jobs):
        assert (root / "src/third_party/OSWorld/cache/task/source").read_text() == "immutable input"
        assert all(json.loads((job / "final-integrity.json").read_text()).values())
        assert json.loads((job / "run-status.json").read_text())["exit_code"] == 0
    assert RepairResources(home / ".local/state/liteagent/repair-resources").status()["occupied_slots"] == 0


def test_owned_cleanup_selects_only_its_owner(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("run_osworld", ROOT / "bin/run-osworld.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    commands = []
    class Process:
        def wait(self): return 0
        def poll(self): return 0
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **kw: Process())
    def execute(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "owned-container\n" if command[1]=="ps" else "", "")
    monkeypatch.setattr(launcher.subprocess, "run", execute)
    with (tmp_path / "log").open("w") as log:
        assert launcher.run_owned(["synthetic"], source=tmp_path, environment={}, log=log,
                                  inherited_fds=(), owner="explicit-owner") == 0
    assert commands == [["docker", "ps", "-aq", "--filter", "label=openapa.run_owner=explicit-owner"],
                        ["docker", "rm", "-fv", "owned-container"]]


def test_cancelled_entrypoint_terminates_runner_and_releases_lease(tmp_path, children):
    root = _fixture_project(tmp_path / "project")
    home = tmp_path / "home"
    home.mkdir()
    qcow = tmp_path / "base.qcow2"
    qcow.touch()
    executables = tmp_path / "executables"
    executables.mkdir()
    docker = executables / "docker"
    docker.write_text('#!/bin/sh\nexit 0\n')
    docker.chmod(0o755)
    job = tmp_path / "run"
    environment = {**os.environ, "HOME": str(home), "QWEN_BASE_URL": "http://synthetic/v1",
                   "PATH": str(executables)+os.pathsep+os.environ["PATH"]}
    process = subprocess.Popen([sys.executable, str(root / "bin/run-osworld.py"),
                                "--orders", "1", "--result-dir", str(job), "--qcow2", str(qcow)],
                               env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    children.append(process)
    wait_until(lambda: (job / "synthetic-started").exists(), [process])
    process.terminate()
    out, err = process.communicate(timeout=15)
    assert process.returncode == 143, (out, err)
    assert json.loads((job / "run-status.json").read_text())["status"] == "interrupted_or_failed"
    assert all(json.loads((job / "final-integrity.json").read_text()).values())
    assert RepairResources(home / ".local/state/liteagent/repair-resources").status()["occupied_slots"] == 0


def test_osworld_snapshot_preserves_evaluator_and_private_selected_cache(tmp_path):
    spec = importlib.util.spec_from_file_location("run_osworld", ROOT / "bin/run-osworld.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    root = _fixture_project(tmp_path / "project")
    original = root / "src/third_party/OSWorld"
    copied = tmp_path / "snapshot"
    seal = launcher.prepare_osworld(original, copied, [{"task_id": "task"}])
    assert not (copied / "cache/other").exists()
    (copied / "cache/task/source").write_text("private change")
    assert (original / "cache/task/source").read_text() == "immutable input"
    assert launcher.osworld_digest(copied) == seal
    (copied / "evaluator.py").write_text("modified evaluator")
    assert launcher.osworld_digest(copied) != seal
