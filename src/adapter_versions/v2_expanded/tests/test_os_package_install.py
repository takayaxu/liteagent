from pathlib import Path
from types import SimpleNamespace

import pytest

from os_adapter import command
from os_adapter.errors import AdapterError


@pytest.mark.parametrize("failure", ["temporary_lock", "persistent_lock", "network"])
def test_ocr_package_install_waits_only_for_bounded_apt_lock(monkeypatch, failure):
    script = (Path(__file__).parents[1] / "os_adapter/deploy/install.sh").read_text()
    installer = script.split("/usr/bin/python3 - <<'PY'\n", 1)[1].split("\nPY", 1)[0]
    elapsed = [0.0]
    waits = []
    calls = []
    stderr = (
        "E: Could not get lock /var/lib/apt/lists/lock. It is held by process 77 (packagekitd)"
        if failure != "network" else "E: Failed to fetch repository index"
    )
    native_error = AdapterError(
        "SUDO_AUTH_FAILED", "privileged command failed",
        {"returncode": 100, "stdout": "", "stderr": stderr}, 422,
    )

    def sudo(arguments, *, timeout):
        calls.append((arguments, timeout))
        if failure != "temporary_lock" or len(calls) == 1:
            raise native_error
        return {"stdout": "done\n", "stderr": ""}

    def sleep(seconds):
        waits.append(seconds)
        elapsed[0] += seconds

    monkeypatch.setattr(command, "CommandRunner", lambda: SimpleNamespace(sudo=sudo))
    monkeypatch.setattr("time.monotonic", lambda: elapsed[0])
    monkeypatch.setattr("time.sleep", sleep)
    if failure == "temporary_lock":
        exec(compile(installer, "install.sh:ocr", "exec"), {})
        assert len(calls) == 3
        assert calls[0] == calls[1]
        assert calls[2][0] == [
            "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y",
            "--no-install-recommends", "tesseract-ocr", "tesseract-ocr-eng",
        ]
        assert waits == [3]
    else:
        with pytest.raises(AdapterError) as caught:
            exec(compile(installer, "install.sh:ocr", "exec"), {})
        assert caught.value is native_error
        assert sum(waits) == (90 if failure == "persistent_lock" else 0)
        if failure == "persistent_lock":
            assert len(calls) > 1
        else:
            assert len(calls) == 1
    assert calls[0] == (["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update"], 45)


def test_ocr_install_keeps_full_budget_after_update_lock_wait(monkeypatch):
    script = (Path(__file__).parents[1] / "os_adapter/deploy/install.sh").read_text()
    installer = script.split("/usr/bin/python3 - <<'PY'\n", 1)[1].split("\nPY", 1)[0]
    elapsed = [0.0]
    calls = []

    def sudo(arguments, *, timeout):
        calls.append((arguments, timeout, elapsed[0]))
        if len(calls) == 1:
            elapsed[0] += 42
            raise AdapterError(
                "SUDO_AUTH_FAILED", "privileged command failed",
                {"returncode": 100, "stderr": "E: Could not get lock /var/lib/apt/lists/lock"},
                422,
            )
        command_seconds = 40 if len(calls) == 2 else 15
        assert timeout >= command_seconds
        elapsed[0] += command_seconds
        return {"stdout": "done\n", "stderr": ""}

    def sleep(seconds):
        elapsed[0] += seconds

    monkeypatch.setattr(command, "CommandRunner", lambda: SimpleNamespace(sudo=sudo))
    monkeypatch.setattr("time.monotonic", lambda: elapsed[0])
    monkeypatch.setattr("time.sleep", sleep)
    exec(compile(installer, "install.sh:ocr", "exec"), {})

    assert [timeout for _, timeout, _ in calls] == [45, 45, 60]
    assert calls[-1][0][2:4] == ["apt-get", "install"]
    assert elapsed[0] == 100
