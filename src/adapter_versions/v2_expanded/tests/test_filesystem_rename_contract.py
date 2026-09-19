from pathlib import Path

import jsonschema
import pytest

from integrations.lite_agent.tool_catalog import DIRECT_ACTION_SCHEMAS
from os_adapter.actions import OSActions
from os_adapter.errors import AdapterError
from os_adapter.schema import validate_action_params
from os_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS


def test_rename_rejects_same_absolute_path(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")

    arguments = {"source": str(source), "destination": str(source)}
    validate_action_params("filesystem.rename", arguments)

    with pytest.raises(AdapterError, match="destination must differ from source"):
        OSActions().rename(arguments, 1)
    assert source.read_text(encoding="utf-8") == "payload"


def test_rename_rejects_path_alias_of_source(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")

    arguments = {
        "source": str(source),
        "destination": str(tmp_path / "nested" / ".." / "source.txt"),
    }
    validate_action_params("filesystem.rename", arguments)

    with pytest.raises(AdapterError, match="destination must differ from source"):
        OSActions().rename(arguments, 1)


def test_rename_rejects_same_inode_even_when_replace_requested(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    alias = tmp_path / "alias.txt"
    source.write_text("payload", encoding="utf-8")
    alias.hardlink_to(source)

    arguments = {
        "source": str(source),
        "destination": str(alias),
        "replace": True,
    }
    validate_action_params("filesystem.rename", arguments)

    with pytest.raises(AdapterError, match="same inode"):
        OSActions().rename(arguments, 1)
    assert source.exists()
    assert alias.exists()


def test_rename_keeps_new_destination_semantics(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    destination = tmp_path / "renamed.txt"
    source.write_text("payload", encoding="utf-8")

    result = OSActions().rename(
        {"source": str(source), "destination": str(destination)}, 1
    )

    assert result == {
        "source": str(source),
        "destination": str(destination),
    }
    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "payload"


def test_rename_rejects_legacy_query_contract_without_mutating(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")
    arguments = {
        "source_query": source.name,
        "new_name": "renamed.txt",
        "search_roots": [str(tmp_path)],
    }

    with pytest.raises(AdapterError, match="unsupported parameters"):
        validate_action_params("filesystem.rename", arguments)
    with pytest.raises(AdapterError, match="only exact source and destination"):
        OSActions().rename(arguments, 1)

    assert source.read_text(encoding="utf-8") == "payload"
    assert not (tmp_path / "renamed.txt").exists()


def _object_schema(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": ["source", "destination"],
        "additionalProperties": False,
    }


def test_public_rename_schemas_share_non_root_path_contract() -> None:
    os_properties = STRICT_ACTION_PARAM_SCHEMAS["filesystem.rename"]["properties"]
    rename_properties = DIRECT_ACTION_SCHEMAS["os"]["filesystem.rename"]["properties"]

    assert DIRECT_ACTION_SCHEMAS["os"]["filesystem.rename"] == (
        STRICT_ACTION_PARAM_SCHEMAS["filesystem.rename"]
    )
    assert set(os_properties) == {"source", "destination", "replace"}
    assert rename_properties["source"]["pattern"] == os_properties["source"]["pattern"]
    assert (
        rename_properties["destination"]["pattern"]
        == os_properties["destination"]["pattern"]
    )

    invalid = {"source": "~/", "destination": "/tmp/renamed.txt"}
    for properties in (os_properties, rename_properties):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, _object_schema(properties))


@pytest.mark.parametrize(
    "source, destination",
    [
        ("/", "/tmp/renamed.txt"),
        ("~/", "/tmp/renamed.txt"),
        ("~", "/tmp/renamed.txt"),
        ("/.", "/tmp/renamed.txt"),
        ("/..", "/tmp/renamed.txt"),
        ("~/.", "/tmp/renamed.txt"),
        ("~/..", "/tmp/renamed.txt"),
        ("/tmp/source.txt", "/"),
        ("/tmp/source.txt", "~/"),
        ("/tmp/source.txt", "~"),
        ("/tmp/source.txt", "/."),
        ("/tmp/source.txt", "/.."),
        ("/tmp/source.txt", "~/./"),
        ("/tmp/source.txt", "~/../"),
    ],
)
def test_os_schema_rejects_root_aliases(source: str, destination: str) -> None:
    with pytest.raises(AdapterError):
        validate_action_params(
            "filesystem.rename", {"source": source, "destination": destination}
        )


@pytest.mark.parametrize(
    "params",
    [
        {"source": "source.txt", "destination": "/tmp/renamed.txt"},
        {"source": "/tmp/source.txt", "destination": "renamed.txt"},
        {"source_query": "source-file", "new_name": "renamed-file"},
        {
            "source": "/tmp/source.txt",
            "destination": "/tmp/renamed.txt",
            "search_roots": ["/tmp"],
        },
    ],
)
def test_rename_schema_rejects_relative_and_legacy_targeting(params: dict) -> None:
    with pytest.raises(AdapterError):
        validate_action_params("filesystem.rename", params)


def test_runtime_rejects_root_and_home_without_mutating(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")
    home = str(Path.home())

    for source_value, destination_value in (
        ("/", str(tmp_path / "renamed.txt")),
        ("~/", str(tmp_path / "renamed.txt")),
        (home, str(tmp_path / "renamed.txt")),
        (str(source), "/"),
        (str(source), "~/"),
        (str(source), home),
    ):
        with pytest.raises(AdapterError):
            OSActions().rename(
                {
                    "source": source_value,
                    "destination": destination_value,
                    "replace": True,
                },
                1,
            )
    assert source.read_text(encoding="utf-8") == "payload"


def test_rename_replaces_a_distinct_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    destination = tmp_path / "renamed.txt"
    source.write_text("new payload", encoding="utf-8")
    destination.write_text("old payload", encoding="utf-8")

    result = OSActions().rename(
        {"source": str(source), "destination": str(destination), "replace": True},
        1,
    )

    assert result["destination"] == str(destination)
    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "new payload"
