"""Prompt-only progress after an observed native Summary Slide operation.

This projection neither creates slides nor decides completion. Source titles and
new page identities come exclusively from executed public tool observations.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .answer_completion_progress import _call
from .atomic_tool_surface import atomic_provider_surface
from .completion_policy import action_is_read_only, effective_canonical_action


def _body(event: Any) -> dict:
    response = event.result if isinstance(event.result, dict) else {}
    hint = response.get("context_hint")
    if isinstance(hint, dict):
        return hint.get("downstream_context", hint)
    return response.get("result", {}) or {}


def _suggest(tools: list[dict], action: str, params: dict) -> dict:
    names = {t.get("function", {}).get("name") for t in tools}
    direct = "adapter__" + action.replace(".", "_")
    if direct in names:
        return {"name": direct, "arguments": params}
    call = _call(tools, "libreoffice_impress", action, params)
    if call.get("name") == "adapter__adapter_call":
        _, bindings = atomic_provider_surface(tools)
        bound = [name for name, binding in bindings.items()
                 if binding.get("adapter") == "libreoffice_impress"
                 and binding.get("action") == action]
        if len(bound) == 1:
            return {"name": bound[0], "arguments": params}
    return call


def model_progress(state: Any, tools: list[dict] | None = None) -> dict | None:
    creation = None
    created_step = save_step = read_step = 0
    inspection = None
    previous_creations = []
    for event in state.events:
        if not event.executed or event.error:
            continue
        if event.proposed.get("kind") == "gui":
            # GUI changes cannot be proven harmless to a generated page here.
            creation = None
            continue
        if event.proposed.get("kind") != "adapter":
            continue
        adapter, action, _ = effective_canonical_action(event, state.domain)
        if adapter != "libreoffice_impress":
            continue
        body = _body(event)
        if action == "slides.create_summary":
            if creation:
                previous_creations.append(creation.get("created_slide_indices", []))
            creation = body
            created_step = event.step
            save_step = read_step = 0
            inspection = None
        elif creation and action == "presentation.save":
            save_step = event.step
        elif creation and action == "presentation.inspect":
            indices = creation.get("created_slide_indices", [])
            slides = body.get("slides", [])
            observed = {s.get("slide", s.get("index")) for s in slides}
            if indices and set(indices).issubset(observed):
                inspection = body
                read_step = event.step
        elif not action_is_read_only(action):
            # Any later edit requires fresh model reasoning; do not endorse an
            # earlier summary observation after its document has changed.
            creation = None
            previous_creations = []
    if not creation or not creation.get("created_slide_indices"):
        return None
    indices = creation["created_slide_indices"]
    progress = {
        "created_step": created_step,
        "created_slide_indices": indices,
        "source_slide_indices": creation.get("effective_source_slides"),
        "observed_native_body": creation.get("native_summary_bodies"),
        "source_titles_match": creation.get("source_titles_match"),
        "source_preservation": creation.get("source_preservation"),
        "latest_save_step": save_step,
        "readback_step": read_step,
        "meaning": "Observed native-operation progress, not task acceptance. "
                   "Check every other instruction clause yourself. Creating again adds another slide; "
                   "it does not verify or replace the first generated slide.",
    }
    if previous_creations:
        progress.update(stage="assess_duplicate_creation",
            previously_created_slide_indices=previous_creations,
            next_step="You ran native summary creation more than once. Compare the requested number "
                      "of summary slides with the actual created indices. Inspect and repair only "
                      "a demonstrated excess; do not run creation again.")
        return progress
    if creation.get("summary_empty") or creation.get("source_titles_match") is not True:
        progress.update(stage="assess_native_result",
            next_step="Inspect the already-created page and its observed source titles. The native "
                      "result has not established a nonempty matching summary. Diagnose the specific "
                      "difference; do not blindly repeat creation.")
        action, params = "presentation.inspect", {"slides": indices}
    elif not save_step:
        progress.update(stage="save_created_summary",
            next_step="The native summary was already created successfully. Save the presentation "
                      "now; do not create another summary or re-inspect the source slides.")
        action, params = "presentation.save", {}
    elif not read_step:
        progress.update(stage="read_created_summary",
            next_step="The native summary is created and saved. Inspect only the returned new page "
                      "indices once and compare its content with the native source-title body.")
        action, params = "presentation.inspect", {"slides": indices}
    else:
        differences = []
        expected_count = creation.get("original_slide_count")
        if isinstance(expected_count, int) and inspection.get("slide_count") != expected_count + len(indices):
            differences.append("Readback slide count differs from original plus created pages.")
        expected_bodies = creation.get("native_summary_bodies", [])
        bodies = []
        for slide in inspection.get("slides", []):
            if slide.get("slide", slide.get("index")) not in indices:
                continue
            bodies.extend("\n".join(str(p.get("text", "")) for p in shape.get("paragraphs", []))
                          for shape in slide.get("text_shapes", [])
                          if str(shape.get("kind", "")).endswith("OutlinerShape"))
        if not expected_bodies or Counter(expected_bodies) != Counter(bodies):
            differences.append("Readback has not established the complete observed native bodies.")
        progress["readback_differences"] = differences
        progress.update(stage="assess_readback" if differences else "review_remaining_clauses",
            next_step=("Address only the concrete readback differences below; do not recreate the summary."
                       if differences else
                       "Creation, saving and matching readback are already recorded. Do not repeat "
                       "inspect/save/create. If this satisfies every user clause and the current "
                       "completion status has no missing items, call propose_done now with these "
                       "executed steps as evidence. Otherwise perform only the specific remaining work."))
        return progress
    call = _suggest(tools or [], action, params)
    if call:
        progress["suggested_tool_call"] = call
    return progress
