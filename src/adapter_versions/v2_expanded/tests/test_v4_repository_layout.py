from pathlib import Path
import subprocess

from scripts import frozen_condition
from scripts import run_lite_agent_pilot as runner
from scripts import strict_runner_support as support
from scripts import supervise_lite_agent_parallel as supervisor


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def initialize(root):
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.name", "Synthetic")
    git(root, "config", "user.email", "synthetic@example.invalid")
    (root / "tracked").write_text("original")
    git(root, "add", "tracked")
    git(root, "commit", "-qm", "synthetic")
    return git(root, "rev-parse", "HEAD")


def test_all_parallel_entrypoints_resolve_current_source_layout():
    project = Path(__file__).resolve().parents[4]
    for module in (frozen_condition, runner, support, supervisor):
        assert module.PROJECT_ROOT == project
    assert runner.OSWORLD_ROOT == support.OSWORLD_ROOT == project / "src/third_party/OSWorld"


def test_frozen_repository_check_uses_pinned_nested_repository(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source_commit = initialize(project)
    osworld = project / "src/third_party/OSWorld"
    pinned_commit = initialize(osworld)
    v2 = project / "src/adapter_versions/v2_expanded"
    v2.mkdir(parents=True)
    monkeypatch.setattr(frozen_condition, "PROJECT_ROOT", project)
    monkeypatch.setattr(frozen_condition, "V2_ROOT", v2)
    config = {"osworld_commit": pinned_commit}
    condition = {"role": "full189", "source_git_commit": source_commit}
    state = frozen_condition._verify_repository_state(config, condition)
    assert state["source_repository"]["toplevel"] == str(project)
    assert state["osworld_repository"]["toplevel"] == str(osworld)
    assert state["source_dirty"] is False
    (osworld / "tracked").write_text("changed")
    import pytest
    with pytest.raises(RuntimeError, match="pinned OSWorld worktree has changes"):
        frozen_condition._verify_repository_state(config, condition)
