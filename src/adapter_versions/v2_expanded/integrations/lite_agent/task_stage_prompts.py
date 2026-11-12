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
                "text", "when_tool", "after_action", "until_action",
            }:
                raise ValueError("unknown task stage prompt fields")
            if not isinstance(stage.get("text"), str) or not stage["text"].strip():
                raise ValueError("task stage prompt text must be nonempty")
            if any(not isinstance(value, str) or not value.strip() for value in stage.values()):
                raise ValueError("task stage prompt fields must be nonempty strings")


def stage_prompt_text(overrides: Any, state: Any, tools: Any) -> str:
    """Select only this exact task's stages from truthful execution/tool state."""
    if not overrides:
        return ""
    names = {tool.get("function", {}).get("name") for tool in (tools or [])}
    texts = []
    for stage in overrides.get(state.task_id, []):
        if stage.get("when_tool") and stage["when_tool"] not in names:
            continue
        if stage.get("after_action") and not state.successful_action_events(stage["after_action"]):
            continue
        if stage.get("until_action") and state.successful_action_events(stage["until_action"]):
            continue
        texts.append(stage["text"])
    return "\n".join(texts)
