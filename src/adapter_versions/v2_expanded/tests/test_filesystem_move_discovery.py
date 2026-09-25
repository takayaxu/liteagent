from __future__ import annotations

import pytest
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState

from integrations.lite_agent.tool_catalog import search_actions


def _os_actions(domain: str, query: str) -> set[str]:
    hits = search_actions(domain, query, strict_generic=True, limit=7)
    return {
        hit["downstream_action"] if domain == "multi_apps" else hit["action"]
        for hit in hits
        if domain != "multi_apps" or hit.get("adapter") == "os"
    }


@pytest.mark.parametrize("domain", ["os", "multi_apps"])
@pytest.mark.parametrize(
    "query",
    [
        "move files and directories into folders",
        "file manager desktop organization",
        "organize files into folders",
    ],
)
def test_move_and_folder_organization_discover_rename(domain: str, query: str) -> None:
    assert "filesystem.rename" in _os_actions(domain, query)


@pytest.mark.parametrize("domain", ["os", "multi_apps"])
def test_explicit_copy_request_keeps_copy_discoverable(domain: str) -> None:
    assert "filesystem.copy" in _os_actions(domain, "copy a file to another folder")


def _organization_state(kind: str = "any") -> RuntimeState:
    state = RuntimeState(
        task_id="organize-test",
        domain="multi_apps",
        instruction="Organize the files and folders on the Desktop into category folders.",
    )
    state.events.append(
        ExecutionEvent(
            step=1,
            timestamp_utc="2026-01-01T00:00:00+00:00",
            proposed={
                "kind": "adapter",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "filesystem.find",
                    "payload": {
                        "params": {
                            "roots": ["~/Desktop"],
                            "kind": kind,
                            "recursive": False,
                        }
                    },
                },
            },
            executed=True,
            result={
                "context_hint": {
                    "downstream_adapter": "os",
                    "downstream_action": "filesystem.find",
                    "downstream_context": {
                        "kind": kind,
                        "truncated": False,
                        "matches": [
                            {"path": "/home/user/Desktop/project", "kind": "directory"},
                            {"path": "/home/user/Desktop/paper.pdf", "kind": "file"},
                        ],
                    },
                }
            },
        )
    )
    return state


def test_kind_any_find_sets_classify_and_move_marker() -> None:
    state = _organization_state()

    marker = state.filesystem_observation_state()

    assert marker is not None
    assert marker["complete"] is True
    assert marker["next_required_phase"] == "classify_and_move"
    assert marker["observed_roots"] == ["~/Desktop"]
    assert {item["path"] for item in marker["observed_entries"]} == {
        "/home/user/Desktop/project",
        "/home/user/Desktop/paper.pdf",
    }
    assert state.context_summary(strict_generic=True)[0]["filesystem_observation"][
        "next_required_phase"
    ] == "classify_and_move"


def test_file_only_find_does_not_mark_observation_complete() -> None:
    assert _organization_state("file").filesystem_observation_state() is None


def test_organization_pending_entries_follow_successful_renames() -> None:
    state = _organization_state()
    state.events.append(
        ExecutionEvent(
            step=2,
            timestamp_utc="2026-01-01T00:00:01+00:00",
            proposed={
                "kind": "adapter",
                "action": "adapter.call",
                "arguments": {
                    "adapter": "os",
                    "action": "filesystem.rename",
                    "payload": {
                        "params": {
                            "source": "/home/user/Desktop/paper.pdf",
                            "destination": "/home/user/Desktop/Paper_reading/paper.pdf",
                        }
                    },
                },
            },
            executed=True,
        )
    )

    assert "/home/user/Desktop/paper.pdf" not in state.filesystem_organization_pending_entries()
    assert state.filesystem_organization_complete() is False
