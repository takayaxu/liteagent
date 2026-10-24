import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.guest_font_profile import GuestFontProfile


class LocalController:
    def __init__(self, tmp_path):
        self.root = tmp_path
        tools = tmp_path / "bin"
        tools.mkdir()
        fake = tools / "fc-match"
        fake.write_text(
            f"#!{sys.executable}\n"
            "import os,pathlib\n"
            "root=pathlib.Path(os.environ['XDG_CONFIG_HOME'])/'fontconfig'/'conf.d'\n"
            "print('Fallback' if list(root.glob('99-liteagent-*.conf')) else 'Original')\n"
        )
        fake.chmod(0o755)
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path / "config"))
        self.env["PATH"] = str(tools) + os.pathsep + self.env["PATH"]

    def execute_python_command(self, code):
        p = subprocess.run(
            [sys.executable, "-c", code], env=self.env,
            capture_output=True, text=True, check=False,
        )
        return {"returncode": p.returncode, "output": p.stdout, "error": p.stderr}


def test_default_profile_does_not_contact_guest():
    profile = GuestFontProfile(None, None)
    assert profile.apply() is None
    assert profile.restore() is None


@pytest.mark.parametrize("config", [
    {}, {"reject_families": "Font", "expected_matches": {"Font": "Fallback"}},
    {"reject_families": [], "expected_matches": {"Font": "Fallback"}},
    {"reject_families": ["Font"], "expected_matches": []},
])
def test_invalid_profile_is_rejected_before_guest_mutation(config):
    with pytest.raises(ValueError):
        GuestFontProfile(None, config)


def test_apply_reset_reapply_and_restore_preserve_existing_config(tmp_path):
    controller = LocalController(tmp_path)
    config_root = tmp_path / "config/fontconfig/conf.d"
    config_root.mkdir(parents=True)
    existing = config_root / "50-existing.conf"
    existing.write_text("keep")
    profile = GuestFontProfile(controller, {
        "reject_families": ["A & B"], "expected_matches": {"Font": "Fallback"},
    })
    first = profile.apply()
    owned = Path(first["path"])
    assert "A &amp; B" in owned.read_text()
    assert first["matches_before"] == {"Font": "Original"}
    assert first["matches_after"] == {"Font": "Fallback"}
    assert profile.apply()["sha256"] == first["sha256"]
    owned.unlink()  # A fresh guest/reset may remove the earlier configuration.
    assert profile.apply()["present"]
    restored = profile.restore()
    assert not restored["present"]
    assert restored["matches_after"] == first["matches_before"]
    assert existing.read_text() == "keep"


def test_wrong_font_match_aborts_and_removes_own_profile(tmp_path):
    profile = GuestFontProfile(LocalController(tmp_path), {
        "reject_families": ["Font"], "expected_matches": {"Font": "Different"},
    })
    with pytest.raises(RuntimeError, match="failed"):
        profile.apply()
    assert not list(tmp_path.glob("config/fontconfig/conf.d/99-liteagent-*.conf"))


def test_cleanup_refuses_changed_file(tmp_path):
    profile = GuestFontProfile(LocalController(tmp_path), {
        "reject_families": ["Font"], "expected_matches": {"Font": "Fallback"},
    })
    owned = Path(profile.apply()["path"])
    owned.write_text("modified externally")
    with pytest.raises(RuntimeError, match="foreign"):
        profile.restore()
    assert owned.read_text() == "modified externally"


def test_guest_failure_is_not_accepted_as_a_receipt():
    class FailedController:
        def execute_python_command(self, code):
            return {"returncode": 1, "output": json.dumps({"operation": "apply"})}

    profile = GuestFontProfile(FailedController(), {
        "reject_families": ["Font"], "expected_matches": {"Font": "Fallback"},
    })
    with pytest.raises(RuntimeError):
        profile.apply()


def test_reset_restores_profile_before_adapter_prepare(monkeypatch):
    from scripts import strict_runner_support as support

    calls = []

    class Env:
        setup_controller = None
        enable_proxy = False

        def reset(self, **kwargs):
            calls.append("reset")
            return "observation"

    monkeypatch.setattr(support, "prepare_adapter_after_reset", lambda *a: calls.append("prepare"))
    monkeypatch.setattr(support, "replay_office_setup", lambda **k: calls.append("replay"))
    env = Env()
    support.install_post_reset_prepare(
        env, "os", {}, before_prepare=lambda: calls.append("fontconfig")
    )
    assert env.reset(task_config={}) == "observation"
    assert calls == ["reset", "fontconfig", "prepare", "replay"]


def test_default_non_office_reset_is_unchanged():
    from scripts.strict_runner_support import install_post_reset_prepare

    class Env:
        def reset(self):
            return "observation"

    env = Env()
    original = env.reset
    install_post_reset_prepare(env, "os", {})
    assert env.reset == original
