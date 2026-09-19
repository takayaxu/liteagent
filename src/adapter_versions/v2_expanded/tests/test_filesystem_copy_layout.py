from pathlib import Path

import pytest

from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.state_model import RuntimeState
from integrations.lite_agent.tool_catalog import build_tools
from os_adapter.actions import OSActions
from os_adapter.errors import AdapterError
from os_adapter.schema import validate_action_params
from os_adapter.worker import execute


@pytest.mark.parametrize("domain", ["os", "multi_apps"])
def test_copy_contract_explains_destination_layout(domain: str) -> None:
    tools = build_tools(
        domain,
        ["filesystem.copy_to_directories"] if domain == "os" else ["adapter.call"],
        strict_generic=True,
        include_gui=False,
        include_control_tools=False,
    )
    if domain == "multi_apps":
        tools = constrain_adapter_call_routes(
            tools, [("os", "filesystem.copy_to_directories")]
        )
        params = tools[0]["function"]["parameters"]["oneOf"][0]["properties"][
            "payload"
        ]["properties"]["params"]
        description = params.get("description", "")
    else:
        description = tools[0]["function"]["description"]
    assert "original basename" in description
    assert "does not recreate the source directory hierarchy" in description
    assert "observed relative path" in description
    assert "same source file" in description
    assert "different source files" in description
    assert "filesystem.copy" in description


def test_copy_uses_only_model_selected_destination_directories(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "nested" / "sample.txt"
    source.parent.mkdir(parents=True)
    source.write_text("synthetic layout content")
    destinations = [tmp_path / "flat", tmp_path / "layout" / "nested"]

    result = OSActions().copy_to_directories(
        {"source": str(source), "destinations": list(map(str, destinations))}, 1
    )

    assert result["copied"] == [str(path / source.name) for path in destinations]
    assert (destinations[0] / source.name).read_text() == source.read_text()
    assert (destinations[1] / source.name).read_text() == source.read_text()
    assert not (destinations[0] / "nested").exists()


@pytest.mark.parametrize("conflict_index", [0, 1])
def test_directory_output_conflict_does_not_copy_any_member(
    tmp_path: Path, conflict_index: int
) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("new source content")
    untouched = tmp_path / "not-created"
    occupied = tmp_path / "occupied"
    conflict = occupied / source.name
    conflict.mkdir(parents=True)
    nested = conflict / source.name
    nested.write_text("preserve this nested file")
    destinations = [untouched]
    destinations.insert(conflict_index, occupied)

    with pytest.raises(AdapterError) as raised:
        OSActions().copy_to_directories(
            {"source": str(source), "destinations": list(map(str, destinations))}, 1
        )

    assert raised.value.code == "DESTINATION_CONFLICT"
    assert str(conflict) in raised.value.message
    assert raised.value.http_status == 409
    assert not untouched.exists()
    assert nested.read_text() == "preserve this nested file"
    assert source.read_text() == "new source content"


def test_copy_to_directories_keeps_existing_regular_file_behavior(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("new source content")
    destination = tmp_path / "output"
    destination.mkdir()
    target = destination / source.name
    target.write_text("old copy")

    result = OSActions().copy_to_directories(
        {"source": str(source), "destinations": [str(destination)]}, 1
    )

    assert result == {"source": str(source), "copied": [str(target)]}
    assert target.read_text() == source.read_text()


@pytest.mark.parametrize("conflict_index", [0, 1])
def test_file_used_as_destination_directory_returns_actionable_conflict(
    tmp_path: Path, conflict_index: int
) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("source content")
    occupied = tmp_path / "existing.txt"
    occupied.write_text("preserve this file")
    untouched = tmp_path / "not-created"
    destinations = [untouched]
    destinations.insert(conflict_index, occupied)

    with pytest.raises(AdapterError) as raised:
        execute({
            "action": "filesystem.copy_to_directories",
            "params": {"source": str(source), "destinations": list(map(str, destinations))},
        })

    assert raised.value.code == "DESTINATION_CONFLICT"
    assert raised.value.http_status == 409
    assert "directory" in raised.value.message
    assert str(occupied) in raised.value.message
    assert "filesystem.copy" in raised.value.details["recovery"]
    assert occupied.read_text() == "preserve this file"
    assert source.read_text() == "source content"
    assert not untouched.exists()


@pytest.mark.parametrize("create_parents", [None, False, True])
def test_single_file_copy_parent_creation_is_opt_in(tmp_path: Path, create_parents) -> None:
    source = tmp_path / "source.txt"
    source.write_text("copy this source")
    destination = tmp_path / "new" / "nested" / "renamed.txt"
    params = {"source": str(source), "destination": str(destination)}
    if create_parents is not None:
        params["create_parents"] = create_parents
    validate_action_params("filesystem.copy", params)

    if create_parents:
        response = execute({"action": "filesystem.copy", "params": params})
        assert response["verification"]["passed"] is True
        assert response["result"]["source"] == params["source"]
        assert response["result"]["destination"] == params["destination"]
        assert destination.read_text() == source.read_text()
    else:
        with pytest.raises(AdapterError) as raised:
            execute({"action": "filesystem.copy", "params": params})
        assert raised.value.code == "PATH_NOT_FOUND"
        assert "create_parents" in raised.value.details["recovery"]
        assert not destination.parent.exists()


def test_copy_parent_creation_does_not_authorize_replacement(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("new content")
    destination = tmp_path / "existing.txt"
    destination.write_text("keep existing content")

    with pytest.raises(AdapterError) as raised:
        execute({
            "action": "filesystem.copy",
            "params": {
                "source": str(source), "destination": str(destination), "create_parents": True,
            },
        })
    assert raised.value.code == "DESTINATION_CONFLICT"
    assert destination.read_text() == "keep existing content"


@pytest.mark.parametrize("domain", ["os", "multi_apps"])
def test_copy_parent_creation_is_exposed_as_an_optional_boolean(domain: str) -> None:
    tools = build_tools(
        domain, ["filesystem.copy"] if domain == "os" else ["adapter.call"],
        strict_generic=True, include_gui=False, include_control_tools=False,
    )
    if domain == "multi_apps":
        tools = constrain_adapter_call_routes(tools, [("os", "filesystem.copy")])
        params = tools[0]["function"]["parameters"]["oneOf"][0]["properties"][
            "payload"
        ]["properties"]["params"]
    else:
        params = tools[0]["function"]["parameters"]
    assert params["properties"]["create_parents"]["type"] == "boolean"
    assert "create_parents" not in params["required"]


def test_collection_copy_keeps_existing_search_and_copy_tools() -> None:
    state = RuntimeState(
        task_id="synthetic-file-layout",
        domain="os",
        instruction=(
            'Copy all files matching "*.bak" in the current directory tree to '
            '"./backup" preserving the directory hierarchy.'
        ),
    )
    agent = LiteAgent(LiteAgentConfig(base_url="http://unused/v1"), object())
    names = {tool["function"]["name"] for tool in agent.tools(state)}
    assert "adapter__filesystem_find" in names
    assert "adapter__filesystem_copy" in names
    assert "adapter__filesystem_copy_to_directories" in names
    assert state.events == []
