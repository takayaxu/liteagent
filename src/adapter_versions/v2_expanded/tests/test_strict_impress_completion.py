from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace
from typing import Any

import pytest

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.completion import CompletionMixin
from integrations.lite_agent.instruction_semantics import (
    content_formatting_argument_contract_errors,
)
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


INSTRUCTION = "Change the picture height to 4, 5, 6 cm on slides 1, 2, 3 respectively."
DOCUMENT_URL = "file:///tmp/synthetic-picture-heights.pptx"


def _picture(path: list[int], height: int) -> dict[str, Any]:
    return {
        "path": path,
        "name": "Synthetic picture",
        "kind": "com.sun.star.drawing.GraphicObjectShape",
        "x": 100,
        "y": 100,
        "width": 5000,
        "height": height,
        "fill_style": "bitmap",
        "is_text": False,
    }


def _slides(heights: list[int]) -> list[dict[str, Any]]:
    return [
        {
            "slide": index,
            "width": 10000,
            "height": 8000,
            "picture_containers": [_picture([index], height)],
            "graphic_shapes": [_picture([index], height)],
            "all_shapes": [_picture([index], height)],
            "text_shapes": [],
        }
        for index, height in enumerate(heights)
    ]


def _event(
    step: int,
    action: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> ExecutionEvent:
    return ExecutionEvent(
        step=step,
        timestamp_utc="2026-09-01T00:00:00Z",
        proposed={"kind": "adapter", "action": action, "arguments": arguments},
        executed=True,
        result=result,
    )


def _inspect(step: int, heights: list[int]) -> ExecutionEvent:
    return _event(
        step,
        "presentation.inspect",
        {},
        {
            "context_hint": {
                "identity": {"url": DOCUMENT_URL},
                "slide_count": len(heights),
                "slides": _slides(heights),
            }
        },
    )


def _resize(step: int, slide: int, height: int) -> ExecutionEvent:
    return _event(
        step,
        "shape.set_geometry",
        {
            "slide": slide,
            "selector": {"path": [slide]},
            "height": height,
        },
        {
            "context_hint": {
                "slide": slide,
                "display_slide_number": slide + 1,
                "resolved_selector": {"path": [slide]},
                "height": height,
                "resolved_geometry": {"height": height},
                "verification_passed": True,
            },
            "adapter_response": {
                "result": {
                    "slide": slide,
                    "display_slide_number": slide + 1,
                    "path": [slide],
                    "resolved_selector": {"path": [slide]},
                    "height": height,
                    "resolved_geometry": {"height": height},
                    "verification_passed": True,
                },
                "status": "ok",
            },
        },
    )


def _save(step: int) -> ExecutionEvent:
    return _event(
        step,
        "presentation.save",
        {"url": DOCUMENT_URL},
        {"status": "ok", "result": {"url": DOCUMENT_URL, "size": 100}},
    )


def _state(events: list[ExecutionEvent]) -> RuntimeState:
    return RuntimeState(
        task_id="synthetic-picture-heights",
        domain="libreoffice_impress",
        instruction=INSTRUCTION,
        events=events,
    )


def _completion() -> dict[str, Any]:
    return {
        "reason": "The requested picture heights were applied.",
        "evidence": ["verified"],
    }


@pytest.mark.parametrize("cleanup", [None, "shape.delete", "slide.delete"])
def test_ordered_image_deck_does_not_require_both_cleanup_strategies(cleanup):
    events = [_inspect(1, [8000])]
    if cleanup is None:
        # This starting page is already empty; no cleanup operation is needed.
        page = events[0].result["context_hint"]["slides"][0]
        for field in ("picture_containers", "graphic_shapes", "all_shapes"):
            page[field] = []
    if cleanup is not None:
        arguments = {"slide": 0}
        if cleanup == "shape.delete":
            arguments["selector"] = {"path": [0]}
        events.append(_event(len(events) + 1, cleanup, arguments, {"status": "ok"}))
    for index in range(0 if cleanup == "slide.delete" else 1, 3):
        events.append(_event(
            len(events) + 1, "slide.create", {"index": index, "layout": 20},
            {"status": "ok"},
        ))
    for index in range(3):
        events.append(_event(
            len(events) + 1, "shape.insert_image",
            {"slide": index, "path": f"/tmp/frame{index + 1}.png"},
            {"status": "ok"},
        ))
    state = RuntimeState(
        task_id="synthetic-ordered-image-deck",
        domain="libreoffice_impress",
        instruction=(
            "The Desktop has frame1.png to frame3.png. Create three blank slides "
            "with one image per slide in numerical order."
        ),
        events=events,
    )
    before_save = CompletionMixin._generic_completion_gate(state)
    assert not before_save["passed"]
    assert any("save" in item for item in before_save["missing"])
    assert not any("have not succeeded" in item for item in before_save["missing"])

    final = _inspect(len(events) + 2, [8000] * 3)
    inventory = final.result["context_hint"]
    inventory["source_images"] = []
    for index, page in enumerate(inventory["slides"]):
        fingerprint = {"status": "known", "algorithm": "sha256-native-dib-v1",
                       "sha256": f"{index:064x}", "pixel_width": 10, "pixel_height": 10}
        page["shape_count"] = 1
        for collection in ("graphic_shapes", "all_shapes", "picture_containers"):
            page[collection][0].update(visible=True, graphic_fingerprint=fingerprint)
        inventory["source_images"].append({"source_path": f"/tmp/frame{index + 1}.png",
                                            "graphic_fingerprint": fingerprint})
    state.events.extend([_save(len(events) + 1), final])
    assert CompletionMixin._generic_completion_gate(state) == {"passed": True, "missing": []}


def test_strict_gate_rejects_an_unfinished_multi_target_picture_request() -> None:
    state = _state(
        [
            _inspect(1, [8000, 8000, 8000]),
            _resize(2, 0, 4000),
            _save(3),
            _inspect(4, [4000, 8000, 8000]),
        ]
    )

    gate = CompletionMixin._generic_completion_gate(state, _completion())

    assert gate["passed"] is False
    assert any("each requested picture" in item for item in gate["missing"])


def test_strict_gate_accepts_all_observation_derived_picture_targets() -> None:
    state = _state(
        [
            _inspect(1, [8000, 8000, 8000]),
            _resize(2, 0, 4000),
            _resize(3, 1, 5000),
            _resize(4, 2, 6000),
            _save(5),
            _inspect(6, [4000, 5000, 6000]),
        ]
    )

    assert CompletionMixin._generic_completion_gate(state, _completion()) == {
        "passed": True,
        "missing": [],
    }


def _content_role_state(action: str) -> RuntimeState:
    arguments = {
        "slides" if action == "slides.format_text_roles" else "slide": [3]
        if action == "slides.format_text_roles"
        else 3,
        "roles": ["content"],
        "font_size": 18,
        "color": "blue",
    }
    return RuntimeState(
        task_id="synthetic-content-role-format",
        domain="libreoffice_impress",
        instruction=(
            "Change the font size of the content on slide 4 to 18, and change the "
            "font color to blue. Change the slide's background to yellow."
        ),
        events=[
            _event(
                1,
                action,
                arguments,
                {
                    "status": "ok",
                    "result": {
                        "slides": [
                            {
                                "slide": 3,
                                "rules": [
                                    {
                                        "normalized_roles": ["content"],
                                        "formatted": [
                                            {"path": [2], "font_size": 18, "color": 255}
                                        ],
                                    }
                                ],
                            }
                        ]
                    },
                },
            ),
            _event(
                2,
                "slide.set_background",
                {"slide": 3, "color": "yellow"},
                {"status": "ok"},
            ),
            _save(3),
            _event(
                4,
                "presentation.inspect",
                {},
                {
                    "context_hint": {
                        "identity": {"url": DOCUMENT_URL},
                        "slide_count": 4,
                        "slides": [
                            {
                                "slide": 3,
                                "background": {
                                    "style": "solid",
                                    "color": 0xFFFF00,
                                },
                            }
                        ],
                    }
                },
            ),
        ],
    )


@pytest.mark.parametrize(
    "action", ["slide.format_text_roles", "slides.format_text_roles"]
)
def test_content_role_completion_accepts_both_public_forms(action: str) -> None:
    state = _content_role_state(action)
    before = deepcopy(state.events)

    assert CompletionMixin._generic_completion_gate(state)["passed"] is True
    assert state.events == before

    state.events = state.events[:2]
    missing = CompletionMixin._generic_completion_gate(state)["missing"]
    assert missing
    assert any("save" in item or "persist" in item for item in missing)
    assert not any("format_text_roles" in item for item in missing)


@pytest.mark.parametrize("unexecuted", [True, False])
def test_content_role_completion_requires_successful_plural_role_evidence(
    unexecuted: bool,
) -> None:
    state = _content_role_state("slides.format_text_roles")
    event = state.events[0]
    if unexecuted:
        event.executed = False
        event.error = {"detail": "rejected", "previous_result": deepcopy(event.result)}
    else:
        event.result["result"]["slides"][0]["rules"][0]["normalized_roles"] = ["title"]

    gate = CompletionMixin._generic_completion_gate(state)
    assert gate["passed"] is False
    assert any("content-only" in item for item in gate["missing"])


def test_later_plural_format_cannot_be_hidden_by_earlier_singular_format() -> None:
    state = _content_role_state("slide.format_text_roles")
    later = _content_role_state("slides.format_text_roles").events[0]
    later.step = 2
    later.proposed["arguments"]["font_size"] = 23
    later.result["result"]["slides"][0]["rules"][0]["formatted"][0]["font_size"] = 23
    for event in state.events[1:]:
        event.step += 1
    state.events.insert(1, later)

    gate = CompletionMixin._generic_completion_gate(state)
    assert gate["passed"] is False
    assert any("content-only" in item for item in gate["missing"])


@pytest.mark.parametrize(
    ("action", "location", "roles"),
    [
        ("slide.format_text_roles", {"slide": 0}, ["all"]),
        ("slides.format_text_roles", {"slides": [0]}, ["all"]),
        ("slide.format_text_roles", {"slide": 0}, ["content", "title"]),
    ],
)
def test_content_only_argument_contract_rejects_non_content_roles(
    action: str, location: dict[str, Any], roles: list[str]
) -> None:
    errors = content_formatting_argument_contract_errors(
        "Change the font size of the content to 12, and change the font color "
        "to orange. Change the slide's background to red.",
        action,
        {
            **location,
            "roles": roles,
            "font_size": 12,
            "color": "orange",
        },
    )

    assert errors
    assert "roles=['content']" in errors[0]


@pytest.mark.parametrize("role", ["content", "body"])
def test_content_only_argument_contract_accepts_content_roles(role: str) -> None:
    assert content_formatting_argument_contract_errors(
        "Change the font size of the content to 12, and change the font color "
        "to orange. Change the slide's background to red.",
        "slide.format_text_roles",
        {"slide": 0, "roles": [role], "font_size": 12, "color": "orange"},
    ) == []


def test_content_only_argument_contract_does_not_block_all_text_request() -> None:
    assert content_formatting_argument_contract_errors(
        "Change every text box to orange and set the slide background to red.",
        "slide.format_text_roles",
        {"slide": 0, "roles": ["all"], "color": "orange"},
    ) == []


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def execute(
        self,
        domain: str,
        action: str,
        arguments: dict[str, Any],
        _metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((domain, action, deepcopy(arguments)))
        return {"executed": True, "result": {"status": "ok"}}


def test_content_only_all_roles_call_is_blocked_before_adapter_execution() -> None:
    state = RuntimeState(
        task_id="synthetic-content-role-contract",
        domain="libreoffice_impress",
        instruction=(
            "Change the font size of the content to 12, and change the font color "
            "to orange. Change the slide's background to red."
        ),
        events=[
            _event(
                1,
                "presentation.inspect",
                {"slides": [0]},
                {"context_hint": {"slide_count": 1, "slides": [{"slide": 0}]}},
            )
        ],
    )
    executor = _RecordingExecutor()
    agent = LiteAgent(
        LiteAgentConfig(base_url="http://unused/v1", include_gui=False),
        executor,
        model_client=SimpleNamespace(client=object()),
    )
    visible_tools = agent.tools(state)

    event = agent.execute_proposal(
        state,
        {
            "tool": "adapter__slide_format_text_roles",
            "arguments_raw": json.dumps(
                {
                    "slide": 0,
                    "roles": ["all"],
                    "font_size": 12,
                    "color": "orange",
                }
            ),
            "_model_visible_tools": visible_tools,
        },
    )

    assert event.executed is False
    assert "roles=['content']" in event.error["detail"]
    assert executor.calls == []
