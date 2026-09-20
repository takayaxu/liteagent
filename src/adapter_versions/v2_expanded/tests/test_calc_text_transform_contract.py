from __future__ import annotations

from types import SimpleNamespace

import pytest

from calc_adapter.errors import AdapterError
from calc_adapter.schema import validate_action_params
from calc_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS
from calc_adapter.uno_worker import _text_transform, _transform_text_value
from integrations.lite_agent.adapter_results import adapter_context_hint
from integrations.lite_agent.tool_catalog import DIRECT_ACTION_SCHEMAS


BASE_PARAMS = {
    "source_sheet": "Raw Titles",
    "source_range": "B2:B4",
    "destination_sheet": "Raw Titles",
    "destination": "C2",
}


def test_text_transform_contract_accepts_exactly_one_transform() -> None:
    contract = STRICT_ACTION_PARAM_SCHEMAS["range.text_transform"]

    assert "transform" in contract["properties"]
    assert "operations" not in contract["properties"]
    assert "transform" in contract["required"]
    assert "title_case changes letter case only" in contract["description"]
    validate_action_params(
        "range.text_transform",
        {**BASE_PARAMS, "transform": "collapse_whitespace"},
    )


def test_text_transform_rejects_legacy_operations_with_recovery_guidance() -> None:
    with pytest.raises(AdapterError) as caught:
        validate_action_params(
            "range.text_transform",
            {
                **BASE_PARAMS,
                "operations": ["collapse_whitespace", "title_case"],
            },
        )

    error = caught.value
    assert error.code == "INVALID_REQUEST"
    assert "once per transform" in error.message
    assert error.details == {
        "conflicting_field": "operations",
        "replacement_field": "transform",
    }


@pytest.mark.parametrize(
    ("transform", "expected"),
    [
        ("trim", "mixed   CASE"),
        ("collapse_whitespace", "mixed CASE"),
        ("title_case", "  Mixed   Case  "),
        ("lowercase", "  mixed   case  "),
        ("uppercase", "  MIXED   CASE  "),
    ],
)
def test_text_transform_applies_one_selected_transform(
    transform: str, expected: str
) -> None:
    assert _transform_text_value("  mixed   CASE  ", transform) == expected


class _Cell:
    def __init__(self, kind: str, value: str = "") -> None:
        self.kind = kind
        self.value = value
        self.writes: list[str] = []

    def getType(self) -> str:
        return self.kind

    def getString(self) -> str:
        return self.value

    def setString(self, value: str) -> None:
        self.writes.append(value)
        self.value = value


class _Range:
    def __init__(self, cells: list[_Cell], start_column: int) -> None:
        self.cells = cells
        self.address = SimpleNamespace(
            StartColumn=start_column,
            EndColumn=start_column,
            StartRow=1,
            EndRow=len(cells),
        )

    def getRangeAddress(self):
        return self.address

    def getCellByPosition(self, column: int, row: int) -> _Cell:
        assert column == 0
        return self.cells[row]


class _Sheet:
    def __init__(self, source: _Range, destination: _Range) -> None:
        self.source = source
        self.destination = destination

    def getCellRangeByName(self, name: str) -> _Range:
        return self.source if name == "B2:B3" else self.destination

    def getCellByPosition(self, column: int, row: int) -> _Cell:
        assert column == 2
        return self.destination.cells[row - 1]


def test_text_transform_preflights_all_sources_before_writing() -> None:
    destination_cells = [_Cell("EMPTY"), _Cell("EMPTY")]
    sheet = _Sheet(
        _Range([_Cell("TEXT", "valid"), _Cell("VALUE", "7")], 1),
        _Range(destination_cells, 2),
    )
    session = SimpleNamespace(sheet=lambda _name: sheet, doc=SimpleNamespace())

    with pytest.raises(AdapterError) as caught:
        _text_transform(
            session,
            {
                "source_sheet": "Sheet1",
                "source_range": "B2:B3",
                "destination_sheet": "Sheet1",
                "destination": "C2",
                "transform": "trim",
            },
        )

    assert caught.value.code == "INVALID_REQUEST"
    assert all(not cell.writes for cell in destination_cells)


def test_text_transform_result_keeps_single_transform_recovery_context() -> None:
    hint = adapter_context_hint(
        "libreoffice_calc",
        "range.text_transform",
        {
            "result": {
                **BASE_PARAMS,
                "destination_range": "C2:C4",
                "transform": "title_case",
                "written_cells": 3,
                "readback": {"display_text": [["One   Title"], ["Two Titles"]]},
            },
            "verification": {"passed": True},
        },
    )

    assert hint is not None
    assert hint["transform"] == "title_case"
    assert hint["destination_range"] == "C2:C4"
    assert hint["display_text"] == [["One   Title"], ["Two Titles"]]
    assert "different transform" in hint["guidance"]
    assert "workbook.save with no fields" in hint["guidance"]


def test_workbook_save_and_save_as_have_separate_contracts() -> None:
    save_contract = DIRECT_ACTION_SCHEMAS["libreoffice_calc"]["workbook.save"]
    save_as_contract = DIRECT_ACTION_SCHEMAS["libreoffice_calc"]["workbook.save_as"]

    assert save_contract["properties"] == {}
    assert save_contract["required"] == []
    assert save_as_contract["required"] == ["url"]
    assert save_as_contract["properties"]["url"]["pattern"]
    validate_action_params("workbook.save", {})

    with pytest.raises(AdapterError) as caught:
        validate_action_params("workbook.save", {"url": "/tmp/cleaned.xlsx"})
    assert caught.value.code == "INVALID_REQUEST"
    assert caught.value.details == {
        "conflicting_fields": ["url"],
        "replacement_action": "workbook.save_as",
    }

    for invalid_url in ("", "{}", ".ods"):
        with pytest.raises(AdapterError) as caught:
            validate_action_params("workbook.save_as", {"url": invalid_url})

        assert caught.value.code == "INVALID_REQUEST"
    validate_action_params("workbook.save_as", {"url": "/tmp/cleaned.xlsx"})
