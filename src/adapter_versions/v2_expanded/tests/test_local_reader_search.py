from __future__ import annotations

import pytest

from integrations.lite_agent.tool_catalog import search_actions


TEXT = ("vs_code", "file.read_text")
TABLE = ("libreoffice_calc", "workbook.read_file")
FIND = ("os", "filesystem.find")


def routes(query, instruction="", **kwargs):
    return [
        (item["adapter"], item["downstream_action"])
        for item in search_actions(
            "multi_apps", query, limit=5, instruction=instruction,
            strict_generic=True, **kwargs,
        )
    ]


@pytest.mark.parametrize("query", [
    "read file parser.py", "read python file text", "read parser.rs",
    "read notes.txt", "read data.tsv", "read file",
])
def test_text_read_search_exposes_reader_before_spreadsheet(query):
    found = routes(query)
    assert TEXT in found
    assert TABLE not in found or found.index(TEXT) < found.index(TABLE)
    assert ("os", "filesystem.create_directory") not in found


def test_explicit_source_read_overrides_incidental_copy_and_spreadsheet_context():
    found = routes(
        "read parser.rs", "Copy the source code into a spreadsheet document."
    )
    assert TEXT in found
    assert TABLE not in found or found.index(TEXT) < found.index(TABLE)
    assert ("os", "filesystem.create_directory") not in found


@pytest.mark.parametrize("query", ["read table.csv", "read table.xlsx", "read table.ods"])
def test_supported_tabular_read_keeps_calc_reader(query):
    found = routes(query, "Inspect the Python source as well.")
    assert TABLE in found
    assert TEXT not in found or found.index(TABLE) < found.index(TEXT)


def test_mixed_extensions_keep_both_readers():
    found = routes("read report.csv and notes.txt")
    assert TEXT in found and TABLE in found


@pytest.mark.parametrize("query, reader", [
    ("extract text report.pdf", ("os", "pdf.extract_text_batch")),
    ("read report.docx", ("libreoffice_writer", "document.read_file")),
])
def test_document_readers_are_not_displaced_by_generic_text(query, reader):
    found = routes(query)
    assert reader in found
    assert TEXT not in found or found.index(reader) < found.index(TEXT)


@pytest.mark.parametrize("query", ["create folder", "make directory", "copy files into folders"])
def test_explicit_organization_is_still_discoverable(query):
    found = routes(query)
    assert ("os", "filesystem.create_directory") in found
    assert ("os", "filesystem.copy") in found


def test_file_discovery_does_not_inherit_copy_operation_from_instruction():
    found = routes("find files", "Copy files into separate folders.")
    assert found[0] == FIND
    assert ("os", "filesystem.create_directory") not in found


def test_named_owner_and_exclusions_still_apply():
    assert routes("libreoffice_calc read file")[0] == TABLE
    assert TEXT not in routes("read notes.txt", excluded_routes=[TEXT])
