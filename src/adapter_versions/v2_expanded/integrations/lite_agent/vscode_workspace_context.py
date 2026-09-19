from __future__ import annotations

from typing import Any


WORKSPACE_MUTATION_ACTIONS = frozenset(
    {
        "workspace.write",
        "workspace.set_folders",
        "workspace.add_folders",
    }
)


def workspace_mutation_context(
    action: str,
    result: dict[str, Any],
    verification: Any,
) -> dict[str, Any] | None:
    if action not in WORKSPACE_MUTATION_ACTIONS:
        return None
    workspace = result.get("workspace")
    if not isinstance(workspace, dict) or not isinstance(
        workspace.get("folders"), list
    ):
        return None

    active = result.get("active_workspace")
    active = active if isinstance(active, dict) else {}
    passed = verification.get("passed") if isinstance(verification, dict) else None
    context = {
        "workspace_file": result.get("path"),
        "workspace_name": active.get("workspace_name"),
        "resolution_source": active.get("resolution_source"),
        "final_folders": workspace["folders"],
        "verification_passed": passed,
    }
    for key in (
        "added_folders",
        "already_present_folders",
    ):
        if key in result:
            context[key] = result[key]
    if isinstance(active.get("workspace_roots"), list):
        context["source_workspace_roots"] = active["workspace_roots"]

    if passed is not True:
        context["guidance"] = (
            "The workspace mutation is not verified. Inspect the reported state and replan; "
            "do not claim completion."
        )
    elif action == "workspace.add_folders":
        context["guidance"] = (
            "The requested folders are now present in the verified saved workspace. "
            "If adding these folders was the whole instruction, propose completion now; "
            "do not repeat this mutation or guess another workspace path."
        )
    else:
        context["guidance"] = (
            "The selected workspace file and final folder list were structurally verified. "
            "If this workspace mutation was the whole instruction, propose completion now; "
            "do not repeat an equivalent write."
        )
    return context
