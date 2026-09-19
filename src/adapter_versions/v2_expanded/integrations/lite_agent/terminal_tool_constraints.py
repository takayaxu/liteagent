"""Instruction-level schema constraints for terminal provenance."""

from __future__ import annotations

import copy
from typing import Any

from .completion_policy import requires_terminal_provenance


def constrain_terminal_provenance_tools(
    tools: list[dict[str, Any]], instruction: str
) -> list[dict[str, Any]]:
    """Require model-selected shell-history provenance when explicitly requested."""
    if not requires_terminal_provenance(instruction):
        return tools

    constrained = copy.deepcopy(tools)
    for tool in constrained:
        function = tool.get("function", {})
        parameters = function.get("parameters", {})
        properties = parameters.get("properties", {})
        provenance = properties.get("provenance")
        if not isinstance(provenance, dict):
            continue
        allowed = provenance.get("enum")
        if isinstance(allowed, list) and "shell_history" not in allowed:
            continue
        provenance["enum"] = ["shell_history"]
        required = parameters.setdefault("required", [])
        if "provenance" not in required:
            required.append("provenance")
        function["description"] += (
            " The instruction explicitly requires command-line or terminal provenance; "
            "select shell_history so the executed command is recorded truthfully."
        )
    return constrained
