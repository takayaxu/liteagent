from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import jsonschema
import pytest

from gimp_adapter.errors import AdapterError
from gimp_adapter.schema import parse_action_request
from gimp_adapter.scriptfu import ScriptFuRunner
from gimp_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS
from gimp_adapter.worker import execute
import gimp_adapter.edit_session as sessions
from types import SimpleNamespace
from PIL import Image, ImageEnhance
from integrations.lite_agent.search_recovery_tools import constrain_adapter_call_routes
from integrations.lite_agent.tool_catalog import build_tools, search_actions


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("make exported photo brighter", ("gimp", "image.set_brightness")),
        ("adjust picture contrast", ("gimp", "image.set_contrast")),
        ("reduce photograph saturation", ("gimp", "image.set_saturation")),
        ("crop image edges", ("gimp", "image.crop")),
        (
            "set slide background image",
            ("libreoffice_impress", "slide.set_background"),
        ),
    ],
)
def test_image_adjustment_search_and_neighboring_operations(query, expected):
    match = search_actions("multi_apps", query, limit=6, strict_generic=True)[0]
    assert (match["adapter"], match["downstream_action"]) == expected


@pytest.mark.parametrize("effect,value", [("brightness", 17), ("contrast", -4), ("saturation", 28.5)])
def test_atomic_adjustment_direct_and_forwarded_contract(effect, value):
    action = "image.set_" + effect
    params = {"image_id": "a" * 32, "value": value}
    assert parse_action_request({"action": action, "params": params}).params == params
    manifest = STRICT_ACTION_PARAM_SCHEMAS[action]
    jsonschema.validate(params, manifest)
    tools = constrain_adapter_call_routes(build_tools("multi_apps", ["adapter.call"],
        include_gui=False, strict_generic=True), [("gimp", action)])
    assert action in json.dumps(tools)
    assert "input_path" not in manifest["properties"]
    assert "output_path" not in manifest["properties"]


@pytest.mark.parametrize("alias", [False, True])
def test_output_collision_preserves_source_and_returns_actionable_error(
    tmp_path, monkeypatch, alias
):
    source = tmp_path / "source.png"
    original = b"synthetic source"
    source.write_bytes(original)
    output = tmp_path / "alias.png" if alias else source
    if alias:
        output.symlink_to(source)
    metadata = Path(str(output) + ".meta.tsv")
    metadata.write_text("preexisting metadata")
    runner = ScriptFuRunner()
    run_scheme = Mock()
    monkeypatch.setattr(runner, "run_scheme", run_scheme)

    with pytest.raises(AdapterError, match="different output_path") as caught:
        runner.export(str(source), str(output), timeout_seconds=1)

    assert caught.value.code == "INVALID_REQUEST"
    assert source.read_bytes() == original
    assert metadata.read_text() == "preexisting metadata"
    run_scheme.assert_not_called()


def test_separate_output_keeps_source_and_existing_artifact_cleanup(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.png"
    output = tmp_path / "result.png"
    metadata = Path(str(output) + ".meta.tsv")
    source.write_bytes(b"synthetic source")
    output.write_bytes(b"stale output")
    metadata.write_text("stale metadata")
    runner = ScriptFuRunner()

    def run_scheme(body, timeout_seconds):
        assert source.read_bytes() == b"synthetic source"
        assert not output.exists()
        assert not metadata.exists()
        assert "gimp-brightness-contrast" not in body
        output.write_bytes(b"synthetic result")
        metadata.write_text("8\t6\tLayer\t8\t6\t0\t0")
        return {"returncode": 0}

    monkeypatch.setattr(runner, "run_scheme", run_scheme)
    result = runner.export(str(source), str(output), timeout_seconds=1)

    assert result["output_path"] == str(output)
    assert result["metadata"]["image_width"] == 8
    assert source.read_bytes() == b"synthetic source"


@pytest.mark.parametrize("adjustments", [
    {"brightness": 10, "contrast": 5},
    {"brightness": 0, "saturation": 20},
    {"brightness": -10, "contrast": 10, "saturation": 5},
])
def test_combined_adjustments_rejected_before_worker_or_script_execution(monkeypatch, adjustments):
    params = {"input_path": "/tmp/source.png", "output_path": "/tmp/result.png", **adjustments}
    assert "image.adjust" not in STRICT_ACTION_PARAM_SCHEMAS
    operation = Mock()
    monkeypatch.setattr(sessions, "execute_session", operation)
    for invoke in (
        lambda: parse_action_request({"action": "image.adjust", "params": params}),
        lambda: execute({"action": "image.adjust", "params": params}),
        lambda: parse_action_request({"action": "image.set_brightness",
            "params": {"image_id": "a" * 32, "value": 10, **adjustments}}),
    ):
        with pytest.raises(AdapterError):
            invoke()
    operation.assert_not_called()


@pytest.mark.parametrize("field", ["brightness", "contrast", "saturation"])
@pytest.mark.parametrize("amount", [-20, 20])
def test_default_adjustment_verification_checks_selected_direction_and_rejects_no_effect(tmp_path, monkeypatch, field, amount):
    monkeypatch.setattr(sessions, "SESSION_ROOT", tmp_path / "private")
    source, output = tmp_path / "source.png", tmp_path / "output.png"
    image = Image.new("RGB", (8, 8))
    image.putdata([(80, 100, 120), (120, 140, 160)] * 32)
    image.save(source)
    runner = SimpleNamespace(_run_image_operation=Mock(return_value={"output_path": str(source)}))
    opened, _ = sessions.execute_session("image.open_session", {"path": str(source)}, runner, None, 1)
    state_file = tmp_path / "private" / opened["image_id"] / "state.json"
    state = json.loads(state_file.read_text())
    state["image"]["preview_path"] = str(source)
    state_file.write_text(json.dumps(state))
    action = "image.set_" + field
    params = {"image_id": opened["image_id"], "value": amount}
    enhancer = {"brightness": ImageEnhance.Brightness, "contrast": ImageEnhance.Contrast, "saturation": ImageEnhance.Color}[field]
    enhancer(image).enhance(1.5 if amount > 0 else 0.5).save(output)
    runner._run_image_operation.return_value = {"output_path": str(output), "preview_path": str(output)}
    result, check = sessions.execute_session(action, params, runner, None, 1)
    assert check["passed"]
    direction = "increased" if amount > 0 else "decreased"
    assert any(c["type"] == f"{field}_{direction}" for c in check["checks"])
    before = state_file.read_bytes()
    with pytest.raises(AdapterError, match="session unchanged"):
        sessions.execute_session(action, params, runner, None, 1)
    assert state_file.read_bytes() == before
