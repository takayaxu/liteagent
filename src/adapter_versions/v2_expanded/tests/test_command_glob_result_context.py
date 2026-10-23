from copy import deepcopy
import json

import pytest

from integrations.lite_agent.adapter_results import command_run_context
from integrations.lite_agent.context_projection import compact_hint
from os_adapter.actions import OSActions


@pytest.mark.parametrize("saved", [False, True])
def test_empty_success_with_literal_glob_warns_without_changing_result(saved):
    result = {"argv": ["sample-converter", "*.txt"], "returncode": 0, "stdout": "", "stderr": ""}
    if saved:
        result.update(stdout_path="/tmp/output.log", stdout_bytes=0)
    original = deepcopy(result)

    context = command_run_context(result)

    assert context["returncode"] == 0
    assert "does not expand wildcard" in context["guidance"]
    assert "does not verify" in context["guidance"]
    assert "native program patterns" in context["guidance"]
    assert "stdout" in context["guidance"]
    assert result == original
    bounded = compact_hint(context, remaining_chars=1800)
    assert "does not expand wildcard" in json.dumps(bounded)


@pytest.mark.parametrize("argv", [
    ["echo", "hello"],
    ["bash", "-c", "echo *.txt"],
    ["/bin/bash", "-lc", "echo *.txt"],
    ["/bin/sh", "-c", "echo *.txt"],
])
def test_ordinary_commands_and_shell_scripts_keep_original_context(argv):
    context = command_run_context({"argv": argv, "returncode": 0})

    assert "does not expand wildcard" not in context["guidance"]


def test_native_pattern_remains_literal_and_successful(tmp_path):
    (tmp_path / "sample.txt").touch()
    params = {
        "argv": ["find", ".", "-name", "*.txt"],
        "cwd_source": "explicit", "cwd_path": str(tmp_path), "provenance": "none",
    }
    original = deepcopy(params)

    result = OSActions().run_command(params, 5)
    context = command_run_context(result)

    assert result["returncode"] == 0
    assert result["stdout"] == "./sample.txt\n"
    assert "unless it interprets patterns itself" in context["guidance"]
    assert params == original
