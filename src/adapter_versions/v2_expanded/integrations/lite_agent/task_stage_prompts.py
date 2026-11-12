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
            if stage.get("facts", "file_copy_ledger") not in {"file_copy_ledger", "pdf_source_ledger"}:
                raise ValueError("unknown task stage facts projection")
            if stage.get("context_mode", "full") not in {"full", "bound_call", "review_call", "structured_observation", "classification_call"}:
                raise ValueError("unknown task stage context_mode")
            if (stage.get("context_mode") == "review_call"
                    and stage.get("when_tool") != "organization__classification_verdict"):
                raise ValueError("review_call requires the classification verdict tool")
            if (stage.get("context_mode") in {"structured_observation", "classification_call"}
                    and stage.get("when_tool") != "organization__verify_current"):
                raise ValueError("structured_observation requires the organization review tool")
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
    if any(stage.get("facts") == "pdf_source_ledger"
           for stage in selected_stages(overrides, state, tools)):
        return _pdf_source_facts(state)
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


def _pdf_source_facts(state: Any) -> str:
    """Reproject observed source windows and exact PDF names, never assignments."""
    import json
    from .adapter_results import has_passed_verification
    from .completion_policy import effective_canonical_action
    from .result_envelopes import iter_result_mappings
    workbooks, forms, writes = [], [], []
    for event in state.successful_adapter_events():
        if not has_passed_verification(event.result):
            continue
        owner, action, arguments = effective_canonical_action(event, state.domain)
        if owner == "libreoffice_calc" and action == "workbook.read_file":
            # Raw successful envelopes retain rows omitted by the generic preview.
            for result in iter_result_mappings(event.result):
                if isinstance(result.get("sheets"), list):
                    workbooks.append({"step": event.step, "path": result.get("path"),
                        "truncated": result.get("truncated"), "sheets": [
                            _source_sheet_facts(sheet) for sheet in result["sheets"] if isinstance(sheet, dict)]})
                    break
        elif owner == "os" and action == "pdf.form.inspect":
            context = (event.result.get("context_hint") or {}).get("downstream_context")
            if isinstance(context, dict) and isinstance(context.get("fields"), list):
                forms.append({"step": event.step, **{key: context[key] for key in (
                    "input_path", "field_offset", "next_offset", "truncated", "context_truncated", "guidance")
                    if key in context}, "fields": [
                        {key: field[key] for key in ("field_name", "field_type", "writable", "value") if key in field}
                        for field in context["fields"] if isinstance(field, dict)]})
        elif owner == "os" and action == "pdf.form.fill":
            writes.append({"step": event.step, "input_path": arguments.get("input_path"),
                "output_path": arguments.get("output_path"), "fields": arguments.get("fields")})
    return "\nCURRENT PDF SOURCE FACTS: " + json.dumps({
        "observed_workbook_reads": workbooks, "observed_pdf_fields": forms,
        "verified_executed_fills": writes}, ensure_ascii=False) + (
        "\nThese are executed observations, not inferred assignments. Use exact field_name strings, "
        "not human labels. Source rows omitted from an earlier preview are retained here. "
        "A successful fill receipt records execution; inspect the saved output before completion.")


def _source_sheet_facts(sheet: dict[str, Any]) -> dict[str, Any]:
    facts = {key: sheet[key] for key in ("name", "returned_range", "truncated", "display_text")
             if key in sheet}
    rows = sheet.get("display_text")
    # Preserve the raw grid. Add a lossless header view only when columns are
    # unambiguous; never infer headers, values, target fields, or output names.
    if isinstance(rows, list) and rows and isinstance(rows[0], list):
        headers = rows[0]
        if (headers and all(isinstance(h, str) and h.strip() for h in headers)
                and len(set(headers)) == len(headers)
                and all(isinstance(row, list) and len(row) == len(headers) for row in rows[1:])):
            facts["source_rows_by_header"] = [dict(zip(headers, row)) for row in rows[1:]]
    return facts


def omit_stage_image(overrides: Any, state: Any, tools: Any) -> bool:
    """Only a scoped native source review can omit an unrelated desktop image."""
    if not any(stage.get("context_mode") in {"structured_observation", "classification_call"}
               for stage in selected_stages(overrides, state, tools)):
        return False
    current = state.filesystem_organization_current_entry()
    if not current:
        return False
    observation = state.filesystem_organization_evidence(current)
    if not observation:
        return False
    action = observation.get("action")
    return bool(action and action != "desktop.open_path"
                and action == state.filesystem_organization_reader_route(current)[1])


def classification_stage_system(overrides: Any, state: Any, tools: Any) -> str | None:
    stages = [stage for stage in selected_stages(overrides, state, tools)
              if stage.get("context_mode") == "classification_call"]
    return "\n".join(stage["text"] for stage in stages) if stages else None


def classification_stage_context(overrides: Any, state: Any, tools: Any) -> str | None:
    if classification_stage_system(overrides, state, tools) is None:
        return None
    current = state.filesystem_organization_current_entry()
    if not current:
        return None
    import json
    from .organization_validation import classification_destinations
    _, excluded = classification_destinations(state, current)
    properties = next((tool.get("function", {}).get("parameters", {}).get("properties", {})
        for tool in (tools or []) if tool.get("function", {}).get("name") == "organization__verify_current"), {})
    latest_check = next((event.result for event in reversed(state.events)
        if isinstance(event.result, dict) and event.result.get("path") == current["path"]
        and isinstance(event.result.get("passed"), bool)), None)
    return "Current source classification facts: " + json.dumps({
        "current_object": current,
        "permitted_destination_directories": properties.get("destination_directory", {}).get("enum"),
        "incompatible_destinations": excluded,
        "current_object_observation": state.filesystem_organization_evidence(current),
        "latest_classification_feedback": latest_check,
        "latest_execution_error": state.events[-1].error if state.events else None,
    }, ensure_ascii=False) + "\nEmit one current review call using the exact permitted directory enum."
