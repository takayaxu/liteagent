"""Explicit per-task prompt experiments; disabled unless configured by the caller."""
from __future__ import annotations

from typing import Any


def validate_task_stage_prompts(overrides: Any) -> None:
    if overrides is None:
        return
    if not isinstance(overrides, dict):
        raise ValueError("task_stage_prompts must map exact task IDs to stage lists")
    for task_id, stages in overrides.items():
        if not isinstance(task_id, str) or not task_id.strip() or not isinstance(stages, list):
            raise ValueError("task_stage_prompts requires exact task IDs and stage lists")
        for stage in stages:
            if not isinstance(stage, dict) or set(stage) - {
                "text", "when_tool", "after_action", "until_action", "context_mode", "facts",
            }:
                raise ValueError("unknown task stage prompt fields")
            if not isinstance(stage.get("text"), str) or not stage["text"].strip():
                raise ValueError("task stage prompt text must be nonempty")
            for key in ("after_action", "until_action"):
                reference = stage.get(key)
                if isinstance(reference, str) and ":" in reference:
                    from integrations.openapa_osworld.tool_catalog import public_actions
                    domain, action = reference.split(":", 1)
                    try:
                        known = action in public_actions(domain)
                    except (KeyError, ValueError):
                        known = False
                    if not known:
                        raise ValueError(f"unknown qualified stage action: {reference}")
            if stage.get("facts", "file_copy_ledger") != "file_copy_ledger":
                raise ValueError("unknown task stage facts projection")
            if stage.get("context_mode", "full") not in {"full", "bound_call"}:
                raise ValueError("unknown task stage context_mode")
            if any(not isinstance(value, str) or not value.strip() for value in stage.values()):
                raise ValueError("task stage prompt fields must be nonempty strings")


def _succeeded(state: Any, action: str) -> bool:
    if ":" not in action:
        return bool(state.successful_action_events(action))
    from .completion_policy import effective_canonical_action, canonical_action_identity
    domain, name = action.split(":", 1)
    identity = canonical_action_identity(domain, name)
    return any(effective_canonical_action(event, state.domain)[:2] == identity
               for event in state.successful_adapter_events())


def selected_stages(overrides: Any, state: Any, tools: Any) -> list[dict[str, str]]:
    """Select only this exact task's stages from truthful execution/tool state."""
    if not overrides:
        return []
    names = {tool.get("function", {}).get("name") for tool in (tools or [])}
    texts = []
    for stage in overrides.get(state.task_id, []):
        if stage.get("when_tool") and stage["when_tool"] not in names:
            continue
        if stage.get("after_action") and not _succeeded(state, stage["after_action"]):
            continue
        if stage.get("until_action") and _succeeded(state, stage["until_action"]):
            continue
        texts.append(stage)
    return texts


def stage_prompt_text(overrides: Any, state: Any, tools: Any) -> str:
    return "\n".join(stage["text"] for stage in selected_stages(overrides, state, tools))


def bound_call_context(overrides: Any, state: Any, tools: Any) -> str | None:
    if not any(stage.get("context_mode") == "bound_call"
               for stage in selected_stages(overrides, state, tools)):
        return None
    if not tools or len(tools) != 1:
        return None
    schema = tools[0].get("function", {}).get("parameters", {})
    if not (schema.get("type") == "object" and schema.get("properties") == {}
            and not schema.get("required") and schema.get("additionalProperties") is False):
        return None
    import json
    observations = [{"step": event.step, "tool": event.proposed.get("tool"),
                     "executed": event.executed, "has_error": bool(event.error)}
                    for event in state.events[-8:]]
    return ("Current stage: one bound call with no editable arguments. "
            "The current tool description states the bound operation. "
            "Emit one tool call with {}. Assess its returned execution result next. "
            "The full native observations remain in the execution ledger. "
            "Recent executed-tool facts: " + json.dumps(observations, ensure_ascii=False))


def stage_fact_text(overrides: Any, state: Any, tools: Any) -> str:
    if not any(stage.get("facts") == "file_copy_ledger"
               for stage in selected_stages(overrides, state, tools)):
        return ""
    import json
    from .adapter_results import has_passed_verification
    from .completion_policy import effective_canonical_action
    opened, copies, last_opened = [], [], None
    for event in state.successful_adapter_events():
        if not has_passed_verification(event.result):
            continue
        domain, action, arguments = effective_canonical_action(event, state.domain)
        if domain != "os":
            continue
        if action == "desktop.open_path":
            path = arguments.get("path")
            if isinstance(path, str) and path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
                last_opened = path
                if path not in opened:
                    opened.append(path)
        elif action == "filesystem.copy":
            source, destination = arguments.get("source"), arguments.get("destination")
            if isinstance(source, str) and isinstance(destination, str):
                pair = {"source": source, "destination": destination}
                if pair not in copies:
                    copies.append(pair)
    facts = {"last_opened_image": last_opened,
             "opened_image_paths": opened, "verified_executed_copies": copies,
             "verified_copy_count": len(copies)}
    return ("\nCURRENT EXECUTED COPY FACTS: " + json.dumps(facts, ensure_ascii=False)
            + "\nOpening an image is neither a copy nor a classification. "
              "Only verified_executed_copies confirms a copy. These facts do not "
              "decide which images should be included. If your current visual "
              "decision is include, compare this exact path with the copy records "
              "and execute its copy before marking it copied. Do not infer copied "
              "files from the number of opened images or from a plan. This is "
              "execution history, not a current directory listing; verify final "
              "membership separately after any deletion or replacement.")
