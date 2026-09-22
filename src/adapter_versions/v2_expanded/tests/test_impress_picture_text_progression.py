from __future__ import annotations

from typing import Any

from integrations.lite_agent import impress_semantics
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


INSTRUCTION = (
    "The height of picture should be 20cm on slide 3 while the font size of all "
    "textboxes should be 40pt on slide 6."
)


def _event(
    step: int,
    action: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> ExecutionEvent:
    return ExecutionEvent(
        step=step,
        timestamp_utc="2026-09-21T00:00:00Z",
        proposed={"kind": "adapter", "action": action, "arguments": arguments},
        executed=True,
        result=result,
    )


def _inspection(
    height: int = 10000,
    step: int = 1,
    *,
    include_picture: bool = True,
    font_size: int = 18,
) -> ExecutionEvent:
    picture = {
        "path": [4],
        "name": "Foreground picture",
        "kind": "com.sun.star.drawing.GraphicObjectShape",
        "width": 20000,
        "height": height,
        "x": 100,
        "y": 100,
        "is_text": False,
    }
    textbox = {
        "path": [0],
        "name": "Textbox",
        "kind": "com.sun.star.presentation.OutlinerShape",
        "lines": ["Observed text"],
        "text_style": {"font_size": font_size},
        "is_text": True,
    }
    slides = []
    if include_picture:
        slides.append(
            {
                "slide": 2,
                "width": 30000,
                "height": 20000,
                "picture_containers": [picture],
                "graphic_shapes": [picture],
                "all_shapes": [picture],
                "text_shapes": [],
            }
        )
    slides.append(
        {
            "slide": 5,
            "width": 30000,
            "height": 20000,
            "recursive_text_shapes": [textbox],
            "text_shapes": [textbox],
            "all_shapes": [textbox],
        }
    )
    return _event(
        step,
        "presentation.inspect",
        {},
        {"context_hint": {"slide_count": 6, "slides": slides}},
    )


def _geometry_mutation() -> ExecutionEvent:
    arguments = {
        "slide": 2,
        "slide_number": 3,
        "selector": {"path": [4]},
        "height_measurement": {"value": 20, "unit": "cm"},
    }
    return _event(
        2,
        "shape.set_geometry",
        arguments,
        {
            "slide": 2,
            "display_slide_number": 3,
            "selector": {"path": [4]},
            "path": [4],
            "height": 20000,
            "resolved_geometry": {"height": 20000},
            "verification_passed": True,
        },
    )


def _text_mutation() -> ExecutionEvent:
    return _event(
        4,
        "slide.format_text_roles",
        {"slide": 5, "roles": ["all"], "font_size": 40},
        {"status": "ok"},
    )


def _save() -> ExecutionEvent:
    return _event(6, "presentation.save", {}, {"status": "ok"})


def _state(events: list[ExecutionEvent]) -> RuntimeState:
    return RuntimeState(
        task_id="order-60-picture-text-progression",
        domain="libreoffice_impress",
        instruction=INSTRUCTION,
        events=events,
    )


def _tools() -> list[dict[str, Any]]:
    return [
        {"function": {"name": "adapter__presentation_inspect"}},
        {"function": {"name": "adapter__shape_set_geometry"}},
        {"function": {"name": "adapter__slide_format_text_roles"}},
        {"function": {"name": "adapter__presentation_save"}},
    ]


def test_picture_success_exposes_only_the_next_text_mutation() -> None:
    state = _state([])
    assert impress_semantics.next_action(state) == "presentation.inspect"

    state.events.append(_inspection())
    assert impress_semantics.next_action(state) == "shape.set_geometry"
    assert impress_semantics.stage_actions(
        state,
        [
            "presentation.inspect",
            "shape.set_geometry",
            "slide.format_text_roles",
            "presentation.save",
        ],
    ) == ["shape.set_geometry"]
    assert [
        tool["function"]["name"]
        for tool in impress_semantics.filter_tools(state, _tools())
    ] == ["adapter__shape_set_geometry"]

    state.events.append(_geometry_mutation())
    assert impress_semantics.next_action(state) == "presentation.inspect"
    assert impress_semantics.stage_actions(
        state,
        [
            "presentation.inspect",
            "shape.set_geometry",
            "slide.format_text_roles",
            "presentation.save",
        ],
    ) == ["presentation.inspect"]
    assert [
        tool["function"]["name"]
        for tool in impress_semantics.filter_tools(state, _tools())
    ] == ["adapter__presentation_inspect"]

    state.events.append(_inspection(height=20000, step=3))
    assert impress_semantics.next_action(state) == "slide.format_text_roles"
    state.events.append(_text_mutation())
    assert impress_semantics.next_action(state) == "presentation.inspect"
    assert impress_semantics.stage_actions(
        state,
        ["presentation.inspect", "presentation.save"],
    ) == ["presentation.inspect"]

    state.events.append(_inspection(height=20000, step=5))
    assert impress_semantics.next_action(state) is None
    assert impress_semantics.stage_actions(
        state,
        ["presentation.inspect", "presentation.save"],
    ) == ["presentation.save"]
    assert [
        tool["function"]["name"]
        for tool in impress_semantics.filter_tools(state, _tools())
    ] == ["adapter__presentation_save"]


def test_final_saved_readback_closes_the_surface_after_one_inspection() -> None:
    state = _state(
        [
            _inspection(),
            _geometry_mutation(),
            _inspection(height=20000, step=3),
            _text_mutation(),
            _inspection(height=20000, step=5, font_size=40),
            _save(),
            _inspection(
                step=7,
                include_picture=False,
                font_size=40,
            ),
        ]
    )

    assert impress_semantics.next_action(state) is None
    assert impress_semantics.stage_actions(
        state,
        [
            "presentation.inspect",
            "shape.set_geometry",
            "slide.format_text_roles",
            "presentation.save",
        ],
    ) == []
    assert impress_semantics.filter_tools(state, _tools()) == []
