from copy import deepcopy
import zipfile

import jsonschema
import pytest

from integrations.lite_agent.adapter_results import adapter_context_hint
from integrations.lite_agent.atomic_tool_surface import atomic_provider_surface, restore_adapter_arguments
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools, search_actions
from integrations.openapa_osworld.tool_catalog import public_actions
from os_adapter.errors import AdapterError
from os_adapter.schema import parse_action_request, validate_action_params
from os_adapter.worker import execute


CREATE = "archive.create_zip"
EXTRACT = "archive.extract_zip"


def _wrapped(routes):
    return constrain_adapter_call_routes(build_tools(
        "multi_apps", ["adapter.call"], include_gui=False, include_control_tools=False,
        strict_generic=True,
    ), [("os", action) for action in routes])


def _execute(action, params):
    parsed = parse_action_request({"action": action, "params": params})
    return execute({"action": parsed.action, "params": parsed.params})


@pytest.mark.parametrize("legacy", [False, True])
def test_create_and_extract_keep_selected_paths_bytes_and_verification(tmp_path, legacy):
    folder = tmp_path / "inputs"
    folder.mkdir()
    contents = {"notes.txt": b"chosen text\n", "chart.bin": bytes(range(256))}
    for name, content in contents.items():
        (folder / name).write_bytes(content)
    params = {"archive_path": str(tmp_path / "selected.zip"),
              "input_paths": [str(folder / name) for name in contents],
              "base_directory": str(folder)}
    create_action = "archive.create_extract" if legacy else CREATE
    if legacy:
        params["mode"] = "create"
    original = deepcopy(params)
    response = _execute(create_action, params)
    assert params == original
    assert response["verification"]["passed"]
    assert response["result"]["archive_path"] == params["archive_path"]
    with zipfile.ZipFile(params["archive_path"]) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == contents
    hint = adapter_context_hint("os", create_action, {"status": "ok", **response})
    assert {item["name"] for item in hint["members"]} == set(contents)
    assert hint["verification_passed"] and hint["integrity_verified"]
    assert CREATE in hint["guidance"]
    with pytest.raises(AdapterError, match="already exists"):
        _execute(create_action, params)
    _execute(create_action, {**params, "overwrite": True})
    destination = tmp_path / "unpacked"
    extract_params = {"archive_path": params["archive_path"],
                      "destination_directory": str(destination)}
    extract_action = "archive.create_extract" if legacy else EXTRACT
    if legacy:
        extract_params["mode"] = "extract"
    extract_original = deepcopy(extract_params)
    result = _execute(extract_action, extract_params)
    assert extract_params == extract_original
    assert result["verification"]["passed"]
    assert {name: (destination / name).read_bytes() for name in contents} == contents
    assert {name: (folder / name).read_bytes() for name in contents} == contents
    with pytest.raises(AdapterError) as conflict:
        _execute(extract_action, extract_params)
    assert conflict.value.code == "DESTINATION_CONFLICT"
    _execute(extract_action, {**extract_params, "overwrite": True})


@pytest.mark.parametrize("surface", ["direct", "wrapper", "atomic"])
@pytest.mark.parametrize("action,params", [
    (CREATE, {"archive_path": "/tmp/chosen.zip", "input_paths": ["/tmp/chosen.txt"]}),
    (EXTRACT, {"archive_path": "/tmp/chosen.zip", "destination_directory": "/tmp/out"}),
])
def test_actual_surfaces_enforce_required_fields_and_reject_mode(surface, action, params):
    if surface == "direct":
        schema = build_tools("os", [action], include_gui=False, include_control_tools=False,
                             strict_generic=True)[0]["function"]["parameters"]
    else:
        tools = _wrapped([action])
        if surface == "atomic":
            tools, bindings = atomic_provider_surface(tools)
            function = tools[0]["function"]
            schema = function["parameters"]
            before = deepcopy(params)
            restored = restore_adapter_arguments(params, bindings[function["name"]])
            assert restored == {"adapter": "os", "action": action, "payload": {"params": before}}
            assert params == before
        else:
            schema = tools[0]["function"]["parameters"]["properties"]["payload"]["properties"]["params"]
    jsonschema.validate(params, schema)
    validate_action_params(action, params)
    wrong_field = "destination_directory" if action == CREATE else "input_paths"
    for bad in ({"archive_path": "/tmp/chosen.zip"}, {**params, "mode": "create"},
                {**params, wrong_field: "/tmp/unwanted"}, {**params, "unknown": True}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
        with pytest.raises(AdapterError):
            validate_action_params(action, bad)


@pytest.mark.parametrize("query,action", [
    ("create zip archive", CREATE), ("create ZIP archive with multiple files", CREATE),
    ("extract zip archive", EXTRACT), ("unzip archive", EXTRACT),
    ("unzip", EXTRACT), ("unzip files", EXTRACT), ("extract files from archive", EXTRACT),
])
@pytest.mark.parametrize("domain", ["os", "multi_apps"])
def test_search_selects_the_requested_zip_primitive(domain, query, action):
    assert {CREATE, EXTRACT, "archive.create_extract"} <= set(public_actions("os"))
    first = search_actions(domain, query, strict_generic=True)[0]
    assert first.get("downstream_action", first["action"]) == action
    tools = _wrapped([CREATE, EXTRACT])
    params = tools[0]["function"]["parameters"]["properties"]["payload"]["properties"]["params"]
    assert CREATE in params["description"] and EXTRACT in params["description"]
    assert "input_paths" in params["description"] and "destination_directory" in params["description"]


@pytest.mark.parametrize("query,action", [
    ("copy archive files to folder", "filesystem.copy_to_directories"),
    ("create folder for archive files", "filesystem.create_directory"),
    ("gzip compress file", "archive.compress_file"),
])
def test_archive_nouns_do_not_override_other_explicit_operations(query, action):
    matches = search_actions("multi_apps", query, strict_generic=True)
    actions = [item.get("downstream_action", item["action"]) for item in matches]
    assert action in actions[:3]
    assert actions[0] not in {CREATE, EXTRACT, "archive.create_extract"}


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "symlink"])
def test_extract_rejects_unsafe_members_before_writing(tmp_path, name):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        if name == "symlink":
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            output.writestr(info, b"../untrusted")
        else:
            output.writestr(name, b"untrusted")
    destination = tmp_path / "destination"
    with pytest.raises(AdapterError) as error:
        _execute(EXTRACT, {"archive_path": str(archive), "destination_directory": str(destination)})
    assert error.value.code == "UNSAFE_ARCHIVE_MEMBER"
    assert not destination.exists()


@pytest.mark.parametrize("fields", [
    {"input_paths": []}, {"input_paths": ["relative.txt"]},
    {"input_paths": ["/tmp/a", "/tmp/a"]}, {"archive_path": "/tmp/out.tar"},
    {"input_paths": [f"/tmp/input-{i}" for i in range(257)]},
    {"archive_path": "relative.zip"}, {"overwrite": "yes"},
])
def test_create_retains_existing_input_constraints(fields):
    params = {"archive_path": "/tmp/out.zip", "input_paths": ["/tmp/a"], **fields}
    with pytest.raises(AdapterError):
        validate_action_params(CREATE, params)
