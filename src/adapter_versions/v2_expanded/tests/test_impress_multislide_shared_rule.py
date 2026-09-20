from __future__ import annotations

from types import SimpleNamespace

import jsonschema
import pytest

from impress_adapter.errors import AdapterError
from impress_adapter.schema import validate_action_params
from impress_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS
from impress_adapter import uno_worker
from integrations.lite_agent.tool_catalog import DIRECT_ACTION_SCHEMAS, build_tools


ACTION = "slides.format_text_roles"


def test_multislide_model_and_runtime_accept_only_one_shared_rule() -> None:
    manifest = STRICT_ACTION_PARAM_SCHEMAS[ACTION]
    direct = DIRECT_ACTION_SCHEMAS["libreoffice_impress"][ACTION]
    exposed = build_tools(
        "libreoffice_impress",
        [ACTION],
        include_gui=False,
        include_control_tools=False,
        strict_generic=True,
    )[0]["function"]["parameters"]
    assert direct == manifest
    for schema in (manifest, exposed):
        assert "overrides" not in schema["properties"]
        jsonschema.Draft202012Validator.check_schema(schema)

    arguments = {"slides": [0, 2], "roles": ["title"], "color": "orange"}
    assert not list(jsonschema.Draft202012Validator(exposed).iter_errors(arguments))
    validate_action_params(ACTION, arguments)

    with pytest.raises(AdapterError) as error:
        validate_action_params(
            ACTION,
            {**arguments, "overrides": [{"roles": ["content"], "bold": True}]},
        )
    assert error.value.code == "INVALID_REQUEST"
    assert "params.overrides" in error.value.message
    assert "separate" in error.value.message


def test_multislide_preflights_all_pages_before_formatting(monkeypatch) -> None:
    pages = {0: object(), 1: object()}
    session = SimpleNamespace(page=lambda index: pages[index])
    changes: list[object] = []

    def matches(page, roles):
        if page is pages[1]:
            return iter(())
        return iter([([0], page, "title")])

    monkeypatch.setattr(uno_worker, "iter_shapes_for_roles", matches)
    monkeypatch.setattr(
        uno_worker,
        "_format_role_shape_text",
        lambda shape, rule: changes.append(shape) or {"text": "title"},
    )
    arguments = {"slides": [0, 1], "roles": ["title"], "bold": True}
    validate_action_params(ACTION, arguments)
    with pytest.raises(AdapterError) as error:
        uno_worker._format_text_roles(session, arguments)
    assert error.value.code == "ROLE_NOT_FOUND"
    assert error.value.details["slide"] == 1
    assert changes == []


def test_multislide_applies_same_rule_and_propagates_verification_failure(
    monkeypatch,
) -> None:
    pages = {0: object(), 2: object()}
    session = SimpleNamespace(page=lambda index: pages[index])
    rules_seen: list[dict] = []
    monkeypatch.setattr(
        uno_worker,
        "iter_shapes_for_roles",
        lambda page, roles: iter([([0], page, "title")]),
    )

    def format_shape(shape, rule):
        rules_seen.append(rule)
        if shape is pages[2] and rule.get("underline"):
            raise AdapterError("VERIFICATION_FAILED", "format did not persist", http_status=422)
        return {"text": "title", "properties": {"CharUnderline": "0"}}

    monkeypatch.setattr(uno_worker, "_format_role_shape_text", format_shape)
    arguments = {"slides": [0, 2], "roles": ["title"], "bold": True}
    result = uno_worker._format_text_roles(session, arguments)
    assert result["formatted_slide_count"] == 2
    assert all(len(page["rules"]) == 1 for page in result["slides"])
    assert rules_seen == [{"roles": ["title"], "bold": True}] * 2

    with pytest.raises(AdapterError) as error:
        uno_worker._format_text_roles(session, {**arguments, "underline": True})
    assert error.value.code == "VERIFICATION_FAILED"
