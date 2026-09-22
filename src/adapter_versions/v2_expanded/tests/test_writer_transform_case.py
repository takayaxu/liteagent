from __future__ import annotations

from types import SimpleNamespace

import jsonschema
import pytest

from integrations.lite_agent.tool_catalog import build_tools, select_actions
from writer_adapter import uno_worker
from writer_adapter.errors import AdapterError
from writer_adapter.schema import validate_action_params


def _paragraph(value: str, *, ignore_writes: bool = False):
    class Paragraph:
        def __init__(self):
            self.value = value

        @property
        def String(self):
            return self.value

        @String.setter
        def String(self, replacement):
            if not ignore_writes:
                self.value = replacement

    return Paragraph()


def test_lowercase_contract_and_native_readback(monkeypatch):
    paragraphs = [_paragraph("STATUS READY"), _paragraph("Mixed Case")]
    params = {"mode": "lower"}
    schema = build_tools(
        "libreoffice_writer",
        ["document.transform_case"],
        include_control_tools=False,
        include_gui=False,
    )[0]["function"]["parameters"]
    jsonschema.validate(params, schema)
    validate_action_params("document.transform_case", params)
    monkeypatch.setattr(uno_worker, "_all_paragraphs", lambda doc: iter(paragraphs))

    result = uno_worker._transform_case(SimpleNamespace(doc=object()), params)

    assert [paragraph.String for paragraph in paragraphs] == [
        "status ready",
        "mixed case",
    ]
    assert result == {
        "mode": "lower",
        "paragraphs_changed": 2,
        "paragraphs_verified": 2,
    }


def test_transform_case_rejects_fields_outside_single_mode():
    with pytest.raises(AdapterError, match="requires only params.mode") as error:
        validate_action_params(
            "document.transform_case", {"mode": "lower", "font_size": 12}
        )

    assert error.value.details == {
        "unexpected": ["font_size"],
        "missing": [],
        "allowed": ["mode"],
    }


def test_transform_case_fails_when_native_write_does_not_persist(monkeypatch):
    paragraphs = [_paragraph("UNCHANGED", ignore_writes=True)]
    monkeypatch.setattr(uno_worker, "_all_paragraphs", lambda doc: iter(paragraphs))

    with pytest.raises(AdapterError, match="did not persist") as error:
        uno_worker._transform_case(SimpleNamespace(doc=object()), {"mode": "lower"})

    assert error.value.code == "VERIFICATION_FAILED"
    assert error.value.details == {
        "mode": "lower",
        "paragraph_count": 1,
        "mismatch_indices": [0],
    }


@pytest.mark.parametrize(
    "instruction",
    [
        "Convert every paragraph in this Writer document to lower case.",
        "Apply title case throughout the Writer document.",
    ],
)
def test_generic_case_requests_rank_transform_action_first(instruction):
    ranked = select_actions("libreoffice_writer", instruction, limit=7)

    assert ranked[:3] == [
        "document.inspect",
        "document.save",
        "document.transform_case",
    ]
