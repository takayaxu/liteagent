from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from chrome_adapter.schema import parse_action_request
from chrome_adapter.errors import AdapterError
from integrations.lite_agent.search_recovery_tools import (
    _downstream_params_schema,
    constrain_adapter_call_routes,
)
from integrations.lite_agent.tool_catalog import build_tools


@pytest.mark.parametrize("action", ["page.read", "page.goto", "page.snapshot"])
def test_forwarded_chrome_page_preserves_required_native_target(action):
    original = build_tools("multi_apps", ["adapter.call"], include_gui=False, strict_generic=True)
    before = deepcopy(original)
    tools = constrain_adapter_call_routes(original, [("chrome", action)])
    schema = next(t["function"]["parameters"] for t in tools
                  if t["function"]["name"] == "adapter__adapter_call")
    params = {"url": "chrome://extensions"} if action == "page.goto" else {}
    call = {"adapter": "chrome", "action": action, "payload": {"params": params}}
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(call))
    call["payload"]["target"] = {"target_id": "observed-tab-id"}
    assert not list(validator.iter_errors(call))
    parse_action_request({"adapter": "chrome", "action": action, **call["payload"]})
    assert original == before


@pytest.mark.parametrize("params,valid", [
    ({}, True),
    ({"locator": {"css": "body"}}, True),
    ({"locator": {"role": "button", "name": "Open", "index": 0, "exact": True}}, True),
    ({"locator": {"text": "Hello", "index": 2}}, True),
    ({"locator": {"url": "chrome://extensions"}}, False),
    ({"locator": {}}, False),
    ({"locator": {"css": "body", "text": "Hello"}}, False),
    ({"locator": {"css": "body", "index": -1}}, False),
])
def test_page_read_locator_projection_matches_native_contract(params, valid):
    schema = _downstream_params_schema("chrome", "page.read")
    assert (not list(Draft202012Validator(schema).iter_errors(params))) is valid
    payload = {"action": "page.read", "params": params,
               "target": {"target_id": "observed-tab-id"}}
    if valid:
        parse_action_request(payload)
    else:
        with pytest.raises(AdapterError, match="locator"):
            parse_action_request(payload)


def test_profile_inspection_does_not_acquire_a_page_target_requirement():
    tools = constrain_adapter_call_routes(
        build_tools("multi_apps", ["adapter.call"], include_gui=False, strict_generic=True),
        [("chrome", "browser.inspect")],
    )
    schema = next(t["function"]["parameters"] for t in tools
                  if t["function"]["name"] == "adapter__adapter_call")
    assert not list(Draft202012Validator(schema).iter_errors({
        "adapter": "chrome", "action": "browser.inspect", "payload": {"params": {}},
    }))
