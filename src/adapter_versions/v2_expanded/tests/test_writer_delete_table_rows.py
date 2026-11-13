from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from writer_adapter import uno_worker
from writer_adapter.errors import AdapterError
from writer_adapter.schema import parse_action_request
from integrations.lite_agent.search_recovery_tools import _downstream_params_schema
from integrations.openapa_osworld.tool_catalog import public_actions


class Rows:
    def __init__(self, table):
        self.table = table
        self.calls = []

    @property
    def Count(self):
        return len(self.table.values)

    def removeByIndex(self, index, count):
        self.calls.append((index, count))
        del self.table.values[index:index + count]


class Table:
    def __init__(self):
        self.Name = "Observed table"
        self.values = [[SimpleNamespace(String=text, font="existing font")]
                       for text in ["first", "second", "third", "fourth"]]
        self.Rows = Rows(self)
        self.Columns = SimpleNamespace(Count=1)

    def getCellNames(self):
        return [f"A{i}" for i in range(1, len(self.values) + 1)]

    def getCellByName(self, name):
        return self.values[int(name[1:]) - 1][0]


def session(table):
    collection = SimpleNamespace(hasByName=lambda name: name == table.Name,
                                 getByName=lambda name: table)
    return SimpleNamespace(doc=SimpleNamespace(getTextTables=lambda: collection), path="/saved.docx")


def test_unordered_noncontiguous_rows_delete_only_selected_original_rows():
    table = Table()
    first, third = table.values[0], table.values[2]
    result = uno_worker._delete_table_rows(session(table), {"name": table.Name, "rows": [2, 4]})
    assert table.Rows.calls == [(3, 1), (1, 1)]
    assert table.values == [first, third]
    assert table.values[0] is first and table.values[1] is third
    assert all(cell.font == "existing font" for row in table.values for cell in row)
    assert result["remaining_text_verified"] is True
    assert result["rows"] == 2


@pytest.mark.parametrize("rows,code", [([5], "ROW_NOT_FOUND"), ([1, 2, 3, 4], "INVALID_REQUEST")])
def test_impossible_deletions_fail_before_any_change(rows, code):
    table = Table()
    with pytest.raises(AdapterError) as error:
        uno_worker._delete_table_rows(session(table), {"name": table.Name, "rows": rows})
    assert error.value.code == code
    assert not table.Rows.calls
    assert table.Rows.Count == 4


def test_noop_uno_deletion_is_not_reported_as_success():
    table = Table()
    table.Rows.removeByIndex = lambda index, count: None
    with pytest.raises(AdapterError, match="remaining table text"):
        uno_worker._delete_table_rows(session(table), {"name": table.Name, "rows": [2]})


@pytest.mark.parametrize("rows", [[], [True], ["2"], [0], [-1], [2, 2]])
def test_schema_and_native_boundary_reject_invalid_row_indices(rows):
    params = {"name": "Observed table", "rows": rows}
    schema = _downstream_params_schema("libreoffice_writer", "table.delete_rows")
    assert list(Draft202012Validator(schema).iter_errors(params))
    with pytest.raises(AdapterError, match="params.rows"):
        parse_action_request({"action": "table.delete_rows", "params": params})


def test_public_operation_and_post_save_verification_require_real_observed_state(monkeypatch):
    assert "table.delete_rows" in public_actions("libreoffice_writer")
    table = Table()
    selected = {"name": table.Name, "rows": [4]}
    parse_action_request({"action": "table.delete_rows", "params": selected})
    result = uno_worker._delete_table_rows(session(table), selected)
    monkeypatch.setattr(uno_worker, "_saved_file_state", lambda path: {"exists": True, "valid": True})
    verify = lambda value: uno_worker._implicit_action_verification("table.delete_rows", session(table), value)["passed"]
    assert verify(result)
    assert not verify({**result, "remaining_text_verified": False})
    table.values.pop()
    assert not verify(result)
