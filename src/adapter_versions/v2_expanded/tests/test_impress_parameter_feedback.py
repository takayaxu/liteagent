"""Rejected parameters must explain the public contract without executing edits."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from impress_adapter.errors import AdapterError
from impress_adapter.schema import parse_action_request
from impress_adapter.service import create_app
from impress_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS
from integrations.lite_agent.context_projection import sanitize


@pytest.mark.parametrize("params", [{"slide": 5}, {"slides": 5}, {"slides": [True]}])
def test_focus_inspection_rejection_explains_array_and_index_without_running(params):
    def never_run(*args, **kwargs):
        raise AssertionError("Rejected parameters must not prepare or execute")

    client = create_app(
        lifecycle=SimpleNamespace(listener_ready=never_run),
        runner=SimpleNamespace(run=never_run),
    ).test_client()
    request = {"request_id": "synthetic-feedback", "action": "presentation.inspect", "params": params}
    original = deepcopy(request)
    response = client.post("/v1/actions", json=request)
    assert response.status_code == 400
    error = response.get_json()["error"]
    assert error["code"] == "INVALID_REQUEST"
    details = error["details"]
    assert details["action"] == "presentation.inspect"
    assert details["location"] == "params"
    assert details["executed"] is False
    assert details["unexpected_fields"] == (["slide"] if "slide" in params else [])
    contract = details["parameter_contract"]
    assert contract["properties"] == STRICT_ACTION_PARAM_SCHEMAS["presentation.inspect"]["properties"]
    assert contract["required"] == []
    assert contract["additionalProperties"] is False
    slides = contract["properties"]["slides"]
    assert slides["type"] == "array"
    assert slides["items"]["type"] == "integer"
    assert slides["items"]["minimum"] == 0
    assert "Zero-based" in slides["items"]["description"]
    assert "example" not in details and "corrected_params" not in details
    assert request == original


def test_other_action_uses_its_own_contract_and_valid_requests_stay_intact():
    params = {"slide": 2, "selector": {"path": [1]}, "paragraph_index": -1, "expected_text": ""}
    original = deepcopy(params)
    with pytest.raises(AdapterError) as raised:
        parse_action_request({"action": "shape.delete_paragraph", "params": params})
    error = raised.value
    assert error.message == "params.paragraph_index must be a non-negative integer"
    contract = error.details["parameter_contract"]
    assert contract["properties"] == STRICT_ACTION_PARAM_SCHEMAS["shape.delete_paragraph"]["properties"]
    assert set(contract["required"]) == {"slide", "selector", "paragraph_index", "expected_text"}
    assert params == original
    corrected = {**params, "paragraph_index": 1}
    assert parse_action_request({"action": "shape.delete_paragraph", "params": corrected}).params == corrected
    assert parse_action_request({"action": "presentation.inspect", "params": {"slides": [5]}}).params == {"slides": [5]}


def test_envelope_errors_do_not_mislabel_a_parameter_failure():
    with pytest.raises(AdapterError) as raised:
        parse_action_request({"action": "presentation.inspect", "timeout_ms": -1})
    assert raised.value.details is None


def test_format_rejection_explains_selection_without_triggering_metadata_filter():
    params = {"slide": 2, "selector": {"path": [1]}, "lines": [0, 1]}
    original = deepcopy(params)
    with pytest.raises(AdapterError) as raised:
        parse_action_request({"action": "shape.format_text", "params": params})
    error = raised.value
    hint = error.details["detail"]
    assert "lines only selects text to format" in hint
    assert "does not delete other lines or paragraphs" in hint
    assert "shape.delete_paragraph" in hint
    assert "16777215" not in hint
    assert error.details["parameter_contract"]["properties"]["color"]["oneOf"][1]["maximum"] == 16777215
    assert sanitize({"error": {"detail": hint}})["error"]["detail"] == hint
    assert sanitize({"error": {"detail": "16777215"}})["error"]["detail"] == "<internal-benchmark-metadata>"
    assert params == original
    assert parse_action_request({"action": "shape.format_text", "params": {**params, "bold": True}}).params["bold"]
