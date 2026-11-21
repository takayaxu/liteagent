"""The retired dual-mode entry must not remain a public or executable route."""
import pytest
from integrations.lite_agent.tool_catalog import search_actions
from integrations.openapa_osworld.tool_catalog import public_actions
from os_adapter.actions import OSActions
from os_adapter.errors import AdapterError
from os_adapter.schema import parse_action_request, validate_action_params
from os_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS

LEGACY = "archive.create_extract"

@pytest.mark.parametrize("domain", ["os", "multi_apps"])
def test_legacy_zip_is_not_discoverable(domain):
    assert LEGACY not in public_actions("os")
    assert LEGACY not in STRICT_ACTION_PARAM_SCHEMAS
    for query in [LEGACY, "create zip archive", "extract zip archive"]:
        assert all(item.get("downstream_action", item["action"]) != LEGACY
                   for item in search_actions(domain, query, strict_generic=True))

@pytest.mark.parametrize("mode", ["create", "extract"])
def test_legacy_zip_rejected_before_any_write(tmp_path, mode):
    output = tmp_path / "must-not-exist.zip"
    params = {"mode": mode, "archive_path": str(output),
              "input_paths": [str(tmp_path / "missing")],
              "destination_directory": str(tmp_path / "unpacked")}
    for call in [lambda: parse_action_request({"action": LEGACY, "params": params}),
                 lambda: validate_action_params(LEGACY, params),
                 lambda: OSActions().dispatch(LEGACY, params, 1)]:
        with pytest.raises(AdapterError) as error:
            call()
        assert error.value.code == "UNSUPPORTED_ACTION"
    assert not output.exists()
    assert not (tmp_path / "unpacked").exists()


def test_archive_actions_reject_cross_mode_fields_with_recovery() -> None:
    with pytest.raises(AdapterError, match="archive.extract_zip"):
        validate_action_params(
            "archive.create_zip",
            {
                "archive_path": "/tmp/a.zip",
                "input_paths": ["/tmp/a"],
                "destination_directory": "/tmp/out",
            },
        )
    with pytest.raises(AdapterError, match="archive.create_zip"):
        validate_action_params(
            "archive.extract_zip",
            {
                "archive_path": "/tmp/a.zip",
                "destination_directory": "/tmp/out",
                "input_paths": ["/tmp/a"],
            },
        )


def test_submission_organization_search_does_not_promote_rename() -> None:
    matches = search_actions("os", "organize files for submission")
    actions = [item["action"] for item in matches]
    assert "filesystem.rename" not in actions
    assert "archive.create_zip" in actions
