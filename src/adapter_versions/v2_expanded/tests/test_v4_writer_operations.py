from types import SimpleNamespace
import jsonschema
import pytest
from writer_adapter.paragraph_dedup import plan_paragraph_deduplication
from writer_adapter.schema import ACTIONS as WRITER_ACTIONS, validate_action_params as validate_writer
from writer_adapter.text_format import set_text_format_in_match
from writer_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS as WRITER_SCHEMAS
from integrations.lite_agent.tool_catalog import build_tools


def test_writer_match_segment_format_resolves_exact_absolute_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = "text.set_format_in_match"
    params = {
        "literal": "H2O",
        "occurrence": 1,
        "match_start_offset": 1,
        "match_end_offset": 2,
        "script": "subscript",
    }
    assert action in WRITER_ACTIONS
    validate_writer(action, params)
    exposed = build_tools(
        "libreoffice_writer", [action], include_gui=False,
        include_control_tools=False, strict_generic=True,
    )[0]["function"]["parameters"]
    assert exposed["properties"] == WRITER_SCHEMAS[action]["properties"]
    assert exposed["required"] == WRITER_SCHEMAS[action]["required"]
    jsonschema.Draft202012Validator.check_schema(exposed)

    paragraphs = [SimpleNamespace(String="H2O heading"), SimpleNamespace(String="Use H2O here")]
    captured: dict = {}
    monkeypatch.setattr("writer_adapter.text_search._body_paragraphs", lambda doc: paragraphs)

    def apply(_session, selected):
        captured.update(selected)
        return {"text": selected["expected_text"], "format": {"script": "subscript"}}

    monkeypatch.setattr("writer_adapter.text_format.set_text_format", apply)
    result = set_text_format_in_match(SimpleNamespace(doc=object()), params)
    assert captured == {
        "paragraph_index": 1,
        "start_offset": 5,
        "end_offset": 6,
        "expected_text": "2",
        "script": "subscript",
    }
    assert result["matched_text"] == "H2O"

def test_writer_record_deduplication_is_one_stable_atomic_operation() -> None:
    rows = [
        "06:01:10,E201,SHS,1",
        "06:06:28,E209,SHS,1",
        "06:19:13,E201,FAN,2",
        "06:20:12,E213,SHS,1",
        "06:28:34,E209,UNI,1",
    ]
    plan = plan_paragraph_deduplication(rows, delimiter=",", key_column=1)
    assert plan["keep_indices"] == [0, 1, 3]
    assert plan["remove_indices"] == [2, 4]
    assert plan["duplicate_keys"] == ["E201", "E209"]

    assert "document.deduplicate_records" in WRITER_ACTIONS
    params = {"delimiter": ",", "key_column": 1}
    validate_writer("document.deduplicate_records", params)
    exposed = build_tools(
        "libreoffice_writer", ["document.deduplicate_records"],
        include_gui=False, include_control_tools=False, strict_generic=True,
    )[0]["function"]["parameters"]
    jsonschema.Draft202012Validator.check_schema(exposed)
    assert exposed["required"] == ["delimiter", "key_column"]
