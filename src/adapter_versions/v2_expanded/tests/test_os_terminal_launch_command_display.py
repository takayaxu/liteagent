from __future__ import annotations

import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from os_adapter.actions import OSActions


@pytest.mark.parametrize("action", ["command.run", "terminal.launch"])
@pytest.mark.parametrize("exit_code", [0, 2])
def test_terminal_launch_displays_shell_escaped_command_and_preserves_argv(
    tmp_path, action: str, exit_code: int
) -> None:
    argv = [
        sys.executable,
        "-c",
        "import sys; print(sys.argv[1]); print('native error output', file=sys.stderr); "
        "raise SystemExit(int(sys.argv[2]))",
        "a value with spaces and 'quotes'",
        str(exit_code),
    ]
    launch_calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> dict[str, object]:
        launch_calls.append(command)
        return {"returncode": 0, "stdout": "", "stderr": "", "duration_ms": 1}

    runner = SimpleNamespace(run=run)
    lifecycle = SimpleNamespace(
        windows=lambda: [
            f"0x456 host {launch_calls[0][1].removeprefix('--title=')}"
        ]
    )
    adapter = OSActions(runner=runner, lifecycle=lifecycle)
    if action == "command.run":
        params = {
            "argv": argv,
            "cwd_source": "explicit",
            "cwd_path": str(tmp_path),
            "provenance": "none",
            "terminal": True,
        }
        result = adapter.run_command(params, 5)
    else:
        result = adapter.launch_terminal({"argv": argv, "cwd": str(tmp_path)}, 5)

    launch = launch_calls[0]
    script_index = launch.index("-c") + 1
    script = launch[script_index]
    displayed_command = launch[script_index + 2]
    assert displayed_command == shlex.join(argv)
    assert launch[script_index + 3 :] == argv
    assert result["argv"] == argv
    assert result["returncode"] == 0
    assert result["terminal"]["launched"] is True

    completed = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            script,
            "osworld-adapter-command",
            displayed_command,
            *argv,
        ],
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=5,
    )
    assert completed.returncode == 0
    assert completed.stdout == (
        f"$ {shlex.join(argv)}\n"
        "a value with spaces and 'quotes'\n"
        f"\n[command exited with status {exit_code}]\n"
    )
    assert completed.stderr == "native error output\n"


@pytest.mark.parametrize("use_shell", [False, True])
def test_command_display_does_not_execute_literal_shell_metacharacters(
    tmp_path, use_shell: bool
) -> None:
    marker = tmp_path / "unintended"
    literal = f"$(touch {marker}) `touch {marker}` ; %s \\n"
    if use_shell:
        argv = ["bash", "-c", 'printf "%s" "$1"', "model-script", literal]
    else:
        argv = ["printf", "%s", literal]
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return {"returncode": 0, "stdout": "", "stderr": "", "duration_ms": 1}

    adapter = OSActions(
        runner=SimpleNamespace(run=run),
        lifecycle=SimpleNamespace(
            windows=lambda: [f"0x456 host {calls[0][1].removeprefix('--title=')}"]
        ),
    )
    adapter.launch_terminal({"argv": argv, "cwd": str(tmp_path)}, 5)
    launch = calls[0]
    completed = subprocess.run(
        launch[launch.index("--") + 1 :],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert completed.stdout == (
        f"$ {shlex.join(argv)}\n{literal}\n[command exited with status 0]\n"
    )
    assert not marker.exists()
