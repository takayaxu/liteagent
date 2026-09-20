from __future__ import annotations

from types import SimpleNamespace

import jsonschema
import pytest

from impress_adapter import uno_worker
from impress_adapter.errors import AdapterError
from impress_adapter.schema import parse_action_request
from impress_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS
from integrations.lite_agent.tool_catalog import DIRECT_ACTION_SCHEMAS, build_tools


ACTION = "slide.format_text_roles"


def _public_schema():
    return build_tools(
        "libreoffice_impress", [ACTION], include_gui=False,
        include_control_tools=False, strict_generic=True,
    )[0]["function"]["parameters"]


def test_single_role_rule_is_the_only_public_and_runtime_contract():
    manifest = STRICT_ACTION_PARAM_SCHEMAS[ACTION]
    assert DIRECT_ACTION_SCHEMAS["libreoffice_impress"][ACTION] == manifest
    exposed = _public_schema()
    assert "overrides" not in exposed["properties"]
    valid = {"slide": 0, "roles": ["all"], "color": "Dark Red 2"}
    jsonschema.validate(valid, exposed)
    assert parse_action_request({"action": ACTION, "params": valid}).params == valid

    combined = {**valid, "overrides": [{"roles": ["content"], "underline": True}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(combined, exposed)
    with pytest.raises(AdapterError, match="params.overrides.*separate.*call"):
        parse_action_request({"action": ACTION, "params": combined})


def test_single_role_rule_applies_only_the_selected_property(monkeypatch):
    shape = SimpleNamespace(name="body")
    monkeypatch.setattr(uno_worker, "iter_shapes_for_roles", lambda _page, _roles: [([0], shape, "content")])
    applied = []

    def format_shape(found, rule):
        applied.append((found, dict(rule)))
        return {"text": "body", "properties": {"CharColor": "8388608"}}

    monkeypatch.setattr(uno_worker, "_format_role_shape_text", format_shape)
    session = SimpleNamespace(page=lambda _index: object())
    result = uno_worker._format_text_roles(
        session, {"slide": 0, "roles": ["all"], "color": "Dark Red 2"}
    )
    assert len(result["rules"]) == 1
    assert applied == [(shape, {"roles": ["all"], "color": "Dark Red 2"})]


def test_single_role_readback_failure_does_not_apply_a_later_rule(monkeypatch):
    text = SimpleNamespace(getString=lambda: "body")
    shape = SimpleNamespace(getText=lambda: text)
    monkeypatch.setattr(uno_worker, "iter_shapes_for_roles", lambda _page, _roles: [([0], shape, "content")])
    calls = []

    def set_properties(_text, properties):
        calls.append(dict(properties))

    monkeypatch.setattr(uno_worker, "_set_text_properties", set_properties)
    monkeypatch.setattr(
        uno_worker, "_read_text_properties",
        lambda _text, keys: {key: 0 for key in keys},
    )
    session = SimpleNamespace(page=lambda _index: object())
    first = uno_worker._format_text_roles(
        session, {"slide": 0, "roles": ["all"], "underline": False}
    )
    assert len(first["rules"]) == 1
    with pytest.raises(AdapterError) as failure:
        uno_worker._format_text_roles(
            session,
            {"slide": 0, "roles": ["content"], "underline": True},
        )
    assert failure.value.code == "VERIFICATION_FAILED"
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert first["rules"][0]["formatted"][0]["properties"]["CharUnderline"] == "0"
