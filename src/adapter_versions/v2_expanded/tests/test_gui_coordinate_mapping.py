from __future__ import annotations

import base64
import copy
import io
import json
import re
from types import SimpleNamespace

import jsonschema
import pytest
from PIL import Image

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.agent_protocol import AgentProtocolMixin
from integrations.lite_agent.gui_actions import (
    gui_action_schema_for_image,
    map_gui_coordinates,
)
from integrations.lite_agent.state_model import RuntimeState
from integrations.lite_agent.tool_catalog import build_tools


def _screenshot(size):
    output = io.BytesIO()
    Image.new("RGB", size, "white").save(output, "PNG")
    return output.getvalue()


def _click(**kwargs):
    return {"action": "click", "fallback_reason": "Click the visible control", **kwargs}


def _agent(gui_executor, model_client=None):
    return LiteAgent(
        LiteAgentConfig(base_url="http://unused"), SimpleNamespace(),
        gui_executor=gui_executor,
        model_client=model_client or SimpleNamespace(client=None),
    )


def _state():
    return RuntimeState(task_id="coordinate-mapping", domain="os", instruction="Click the visible button.")


def test_proposal_uses_the_encoded_image_frame_and_execution_scales_once():
    screenshot = _screenshot((1920, 1080))
    raw = _click(x="100", y="230")
    requests = []
    executed = []

    def propose(**request):
        requests.append(request)
        return {"tool": "gui_action", "arguments_raw": json.dumps(raw)}

    def execute(arguments):
        executed.append(arguments)
        return {"executed": True, "result": {"environment_acknowledged": True}}

    agent = _agent(execute, SimpleNamespace(client=None, propose=propose))
    agent.tools = lambda _state: build_tools("os", [], include_gui=True)
    state = _state()
    proposal = agent.propose(state, screenshot)
    content = requests[0]["messages"][-1]["content"]
    encoded = content[1]["image_url"]["url"].split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        assert image.size == (1280, 720)
    assert "1280x720" in content[0]["text"]
    assert "x/to_x from 0 to 1279" in content[0]["text"]
    frame = {"model_size": [1280, 720], "desktop_size": [1920, 1080]}
    assert proposal["_gui_coordinate_frame"] == frame
    request_schema = next(
        tool["function"]["parameters"]
        for tool in requests[0]["tools"]
        if tool["function"]["name"] == "gui_action"
    )
    for action in request_schema["oneOf"]:
        for field, maximum in (("x", 1279), ("y", 719), ("to_x", 1279), ("to_y", 719)):
            coordinate = action["properties"].get(field)
            if coordinate is not None:
                assert coordinate["anyOf"][0]["maximum"] == maximum

    # The proposal owns its exact frame even if the next request changes it.
    agent._messages(state, _screenshot((800, 600)), tools=agent.tools(state))
    event = agent.execute_proposal(state, proposal, screenshot=screenshot)

    assert event.executed, event.error
    assert event.proposed["arguments"] == raw
    assert event.proposed["arguments_raw"] == json.dumps(raw)
    assert event.proposed["gui_coordinate_frame"] == frame
    assert event.proposed["gui_arguments"]["x"] == 150
    assert event.proposed["gui_arguments"]["y"] == 345
    assert executed[0]["command"] == "pyautogui.click(150, 345)"
    assert (executed[0]["x"], executed[0]["y"]) == (150, 345)


@pytest.mark.parametrize("action", ["click", "double_click", "drag"])
def test_all_pointer_positions_are_mapped_without_mutating_arguments(action):
    raw = {**_click(x="640", y="360"), "action": action}
    if action == "drag":
        raw.update(to_x="1279", to_y="719")
    before = copy.deepcopy(raw)
    payloads = []
    agent = _agent(lambda args: payloads.append(args) or {"executed": True})
    event = agent.execute_proposal(
        _state(), {"tool": "gui_action", "arguments_raw": json.dumps(raw)},
        screenshot=_screenshot((1920, 1080)),
    )
    assert event.executed, event.error
    assert raw == before
    assert (payloads[0]["x"], payloads[0]["y"]) == (960, 540)
    if action == "drag":
        assert (payloads[0]["to_x"], payloads[0]["to_y"]) == (1919, 1079)
        assert payloads[0]["command"] == (
            "pyautogui.moveTo(960, 540); pyautogui.dragTo(1919, 1079, duration=0.5)"
        )


@pytest.mark.parametrize("size", [(800, 600), (1280, 720), (2560, 1440), (777, 1601)])
def test_mapping_uses_actual_encoded_dimensions_including_portrait_rounding(size):
    url, frame = AgentProtocolMixin._prepare_model_image(_screenshot(size))
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        assert list(image.size) == frame["model_size"]
    assert list(size) == frame["desktop_size"]
    width, height = frame["model_size"]
    x, y = width // 2, height // 2
    mapped = map_gui_coordinates(_click(x=x, y=y), frame)
    assert abs(mapped["x"] - x * size[0] / width) <= 0.5
    assert abs(mapped["y"] - y * size[1] / height) <= 0.5
    assert map_gui_coordinates(_click(x=0, y=0), frame)["x"] == 0
    if size[0] <= 1280 and size[1] <= 720:
        assert (mapped["x"], mapped["y"]) == (x, y)


@pytest.mark.parametrize("coordinates", [{"x": 1280, "y": 0}, {"x": 0, "y": 720}])
def test_out_of_image_coordinates_never_reach_executor(coordinates):
    payloads = []
    agent = _agent(lambda args: payloads.append(args) or {"executed": True})
    event = agent.execute_proposal(
        _state(), {"tool": "gui_action", "arguments_raw": json.dumps(_click(**coordinates))},
        screenshot=_screenshot((1920, 1080)),
    )
    assert not event.executed
    assert "outside the model image" in event.error["detail"]
    assert not payloads


def test_stale_frame_never_reaches_executor():
    payloads = []
    agent = _agent(lambda args: payloads.append(args) or {"executed": True})
    event = agent.execute_proposal(
        _state(), {
            "tool": "gui_action",
            "arguments_raw": json.dumps(_click(x=818, y=230)),
            "_gui_coordinate_frame": {
                "model_size": [800, 600], "desktop_size": [800, 600],
            },
        },
        screenshot=_screenshot((1920, 1080)),
    )
    assert not event.executed
    assert "does not match the current screenshot" in event.error["detail"]
    assert not payloads


def test_non_pointer_actions_keep_their_values():
    frame = {"model_size": [1280, 720], "desktop_size": [1920, 1080]}
    for fields in ({"action": "scroll", "amount": -3},
                   {"action": "type", "text": "123"},
                   {"action": "hotkey", "keys": ["alt", "f4"]}):
        arguments = {"fallback_reason": "Operate the visible control", **fields}
        assert map_gui_coordinates(arguments, frame) == arguments


@pytest.mark.parametrize(
    ("action", "fields"),
    [
        ("click", {"x": 1279, "y": 719}),
        ("double_click", {"x": "1279", "y": "0719"}),
        ("drag", {"x": 1279, "y": "719", "to_x": "1279", "to_y": 719}),
    ],
)
def test_frame_schema_accepts_in_range_integer_and_string_coordinates(action, fields):
    schema = gui_action_schema_for_image(1280, 720)
    arguments = {"action": action, "fallback_reason": "Click a visible control", **fields}
    jsonschema.validate(arguments, schema)


@pytest.mark.parametrize(
    ("action", "fields"),
    [
        ("click", {"x": 1280, "y": 0}),
        ("click", {"x": 0, "y": "720"}),
        ("double_click", {"x": "1280", "y": 0}),
        ("drag", {"x": 0, "y": 0, "to_x": 1280, "to_y": 0}),
        ("drag", {"x": 0, "y": 0, "to_x": 0, "to_y": "720"}),
    ],
)
def test_frame_schema_rejects_out_of_range_integer_and_string_coordinates(action, fields):
    schema = gui_action_schema_for_image(1280, 720)
    arguments = {"action": action, "fallback_reason": "Click a visible control", **fields}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(arguments, schema)


def test_frame_schema_rejects_invalid_dimensions():
    for size in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="positive integers"):
            gui_action_schema_for_image(size, 720)


@pytest.mark.parametrize("size", [1, 2, 9, 10, 11, 100, 101, 720, 1280])
def test_decimal_string_bounds_match_numeric_bounds(size):
    coordinate = gui_action_schema_for_image(size, 1)["oneOf"][0]["properties"]["x"]
    pattern = coordinate["anyOf"][1]["pattern"]
    for value in range(size + 20):
        assert bool(re.fullmatch(pattern, str(value))) == (value < size)
        assert bool(re.fullmatch(pattern, "000" + str(value))) == (value < size)


def test_request_bounds_follow_latest_image_without_mutating_catalog():
    catalog = build_tools("os", [], include_gui=True)
    original = copy.deepcopy(catalog)
    requests = []

    def propose(**request):
        requests.append(request)
        return {"tool": "gui_action", "arguments_raw": json.dumps(_click(x=0, y=0))}

    agent = _agent(None, SimpleNamespace(client=None, propose=propose))
    agent.tools = lambda _state: catalog
    for size in ((1920, 1080), (800, 600), (777, 1601)):
        proposal = agent.propose(_state(), _screenshot(size))
        schema = next(
            tool["function"]["parameters"]
            for tool in requests[-1]["tools"]
            if tool["function"]["name"] == "gui_action"
        )
        width, height = proposal["_gui_coordinate_frame"]["model_size"]
        for field, maximum in (("x", width - 1), ("y", height - 1)):
            assert schema["oneOf"][0]["properties"][field]["anyOf"][0]["maximum"] == maximum
    # A turn with no decodable image must not reuse a previous frame or bounds.
    proposal = agent.propose(_state(), b"synthetic non-image")
    assert "_gui_coordinate_frame" not in proposal
    assert requests[-1]["tools"] == original
    assert catalog == original
