from __future__ import annotations

from typing import Any
from types import SimpleNamespace

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState
from integrations.lite_agent.tool_catalog import build_tools


INSTRUCTION = (
    "Set the font color of the title in slides 2 to 3 as black and bold the title. "
    "Also, delete the personal information (including the icons) in slide 4."
)


def _event(
    step: int,
    action: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> ExecutionEvent:
    return ExecutionEvent(
        step=step,
        timestamp_utc="2026-10-03T00:00:00Z",
        proposed={"kind": "adapter", "action": action, "arguments": arguments},
        executed=True,
        result=result,
    )


def _title(path: list[int], text: str) -> dict[str, Any]:
    return {
        "path": path,
        "kind": "com.sun.star.drawing.CustomShape",
        "x": 100,
        "y": 100,
        "lines": [text],
        "text_style": {"color": -1, "bold": False, "bold_weight": 100},
    }


def _initial_inspection() -> ExecutionEvent:
    title_one = _title([5], "First title")
    title_two = _title([14], "Second title")
    icon = {
        "path": [1],
        "kind": "com.sun.star.drawing.CustomShape",
        "x": 100,
        "y": 100,
        "width": 20,
        "height": 20,
    }
    phone = {
        "path": [2],
        "kind": "com.sun.star.drawing.CustomShape",
        "x": 500,
        "y": 60,
        "width": 300,
        "height": 100,
        "lines": ["123-456-7890"],
    }
    background = {
        "path": [0],
        "kind": "com.sun.star.drawing.GraphicObjectShape",
        "x": 0,
        "y": 0,
        "width": 10000,
        "height": 8000,
    }
    return _event(
        1,
        "presentation.inspect",
        {},
        {
            "context_hint": {
                "identity": {"url": "file:///tmp/cleanup.pptx"},
                "slide_count": 4,
                "slides": [
                    {
                        "slide": 1,
                        "text_shapes": [title_one],
                        "all_shapes": [title_one],
                    },
                    {
                        "slide": 2,
                        "text_shapes": [title_two],
                        "all_shapes": [title_two],
                    },
                    {
                        "slide": 3,
                        "width": 10000,
                        "height": 8000,
                        "shape_count": 3,
                        "text_shapes": [phone],
                        "all_shapes": [background, icon, phone],
                    },
                ],
            }
        },
    )


def _final_inspection(step: int) -> ExecutionEvent:
    title_one = _title([5], "First title")
    title_two = _title([14], "Second title")
    for title in (title_one, title_two):
        title["text_style"] = {"color": 0, "bold": True, "bold_weight": 150}
    background = {
        "path": [0],
        "kind": "com.sun.star.drawing.GraphicObjectShape",
        "x": 0,
        "y": 0,
        "width": 10000,
        "height": 8000,
    }
    return _event(
        step,
        "presentation.inspect",
        {},
        {
            "context_hint": {
                "identity": {"url": "file:///tmp/cleanup.pptx"},
                "slide_count": 4,
                "slides": [
                    {"slide": 1, "text_shapes": [title_one]},
                    {"slide": 2, "text_shapes": [title_two]},
                    {"slide": 3, "shape_count": 1, "text_shapes": [], "all_shapes": [background]},
                ],
            }
        },
    )


def _cleanup_state() -> RuntimeState:
    state = RuntimeState(
        task_id="synthetic-cleanup",
        domain="libreoffice_impress",
        instruction=INSTRUCTION,
        events=[_initial_inspection()],
    )
    plan = state.title_range_personal_info_cleanup_plan()
    assert plan is not None
    step = 2
    for planned in plan["steps"]:
        state.events.append(_event(step, planned["action"], planned["arguments"], {"status": "ok"}))
        step += 1
    return state


class _Executor:
    def execute(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"executed": True, "result": {"status": "ok"}}


def _agent() -> LiteAgent:
    return LiteAgent(
        LiteAgentConfig(base_url="http://unused/v1", include_gui=False),
        _Executor(),
        model_client=SimpleNamespace(client=object()),
    )


def test_cleanup_completion_forces_save_then_readback_then_done() -> None:
    state = _cleanup_state()
    agent = _agent()

    assert agent.selected_actions(state) == ["presentation.save"]

    state.events.append(_event(10, "presentation.save", {}, {"status": "ok"}))
    assert agent.selected_actions(state) == ["presentation.inspect"]

    state.events.append(_final_inspection(11))
    assert agent.selected_actions(state) == ["propose_done"]


def test_cleanup_completion_uses_native_control_tool_name() -> None:
    tools = build_tools(
        "libreoffice_impress",
        ["propose_done"],
        include_gui=False,
        include_control_tools=True,
        strict_generic=True,
    )
    names = [tool["function"]["name"] for tool in tools]
    assert "propose_done" in names
    assert "adapter__propose_done" not in names


def test_cleanup_readback_requires_all_task_slides() -> None:
    state = _cleanup_state()
    state.events.append(_event(10, "presentation.save", {}, {"status": "ok"}))
    agent = _agent()

    inspect = next(
        tool
        for tool in agent.tools(state)
        if tool["function"]["name"] == "adapter__presentation_inspect"
    )
    assert inspect["function"]["parameters"]["properties"]["slides"]["const"] == [
        1,
        2,
        3,
    ]

    state.events.append(_final_inspection(11))
    assert [tool["function"]["name"] for tool in agent.tools(state)] == [
        "propose_done"
    ]
