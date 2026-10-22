"""Focused contracts for all-target permissions and repair tool availability."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from os_adapter.actions import OSActions
from integrations.lite_agent.adapter_results import adapter_context_hint, compact_adapter_body
from integrations.lite_agent.agent import LiteAgent, LiteAgentConfig
from integrations.lite_agent.completion_outcomes import completion_outcome_issues, outcome_retry_allowed
from integrations.lite_agent.completion_policy import completion_claim_contradictions
from integrations.lite_agent.episode_control import mark_tool_result_for_audit
from integrations.lite_agent.state_model import ExecutionEvent, RuntimeState


def event(step, action, args, result):
    return ExecutionEvent(step=step, timestamp_utc="2031-01-01T00:00:00Z",
                          proposed={"kind": "adapter", "action": action, "arguments": args},
                          parsed=True, validated=True, executed=True, result={"context_hint": result})


def inventory(root="/data/work", modes=("0755", "0640", "0777")):
    return {"roots": [root], "name_patterns": ["*"], "kind": "file", "recursive": True,
            "scan_complete": True, "include_hidden": True, "max_depth": 4,
            "match_count": 3, "returned_count": 3, "truncated": False,
            "matches": [{"path": f"{root}/{name}", "kind": "file", "is_symlink": False, "mode": mode}
                        for name, mode in zip(["one", "nested/two", "deep/three"], modes)]}


def state():
    scan = inventory()
    return RuntimeState(task_id="synthetic-all-permissions", domain="os", working_directory="/data/work",
                        instruction="Change the permission of all regular files under current directory tree to 640",
                        events=[event(1, "filesystem.find", {"roots": ["/data/work"], "name_patterns": ["*"]}, scan),
                                event(2, "filesystem.set_permissions", {"path": "/data/work/one", "mode": "640"},
                                      {"path": "/data/work/one", "mode": "0640", "verification_passed": True})])


def agent(executor=None):
    class NoExecution:
        def execute(self, *_args):
            raise AssertionError("Tool construction must not execute repairs")
    return LiteAgent(LiteAgentConfig(base_url="http://unused/v1", include_gui=False),
                     executor or NoExecution(), model_client=SimpleNamespace(client=object()))


def names(worker, current):
    return {t["function"]["name"] for t in worker.tools(current)}


def final_scan(current, modes=("0640", "0640", "0640")):
    current.events.append(event(len(current.events) + 1, "filesystem.find",
                                {"roots": ["/data/work"], "name_patterns": ["*"], "recursive": True},
                                inventory(modes=modes)))


def test_one_verified_target_cannot_certify_the_batch_or_hide_repair_tools():
    current = state()
    worker = agent()
    gate = worker._generic_completion_gate(current)
    assert not gate["passed"]
    issues = gate["outcome_issues"]
    wrong = [i for i in issues if i["code"] == "permissions.mode_mismatch"]
    assert [i["target"]["path"] for i in wrong] == ["/data/work/deep/three"]
    # The already-correct second target needs no mutation.
    assert not any(i["target"] == {"path": "/data/work/nested/two"} for i in issues)
    assert {"adapter__filesystem_find", "adapter__filesystem_set_permissions", "tools_search"} <= names(worker, current)
    assert current.completion_rejections == 0
    assert current.workflow_progress()["pending_phase"] == "outcome_verification"
    assert worker._generic_completion_gate(current, {"reason": "All modes are correct.", "evidence": "verified"})["passed"] is False


def test_rejected_claim_preserves_concrete_issues_and_allows_direct_model_repair():
    current = state()
    calls = []

    class Executor:
        def execute(self, domain, action, arguments, metadata):
            calls.append((action, deepcopy(arguments)))
            return {"executed": True, "result": {"path": arguments["path"], "mode": "0640", "verification_passed": True}}

    worker = agent(Executor())
    result = worker.execute_proposal(current, {"tool": "propose_done", "arguments_raw": json.dumps({
        "reason": "The remaining files still need to be processed.", "evidence": "One target verified."}),
        "_model_visible_tools": worker.tools(current)})
    assert not result.executed
    assert result.error["outcome_issues"]
    args = {"path": "/data/work/deep/three", "mode": "640"}
    fixed = worker.execute_proposal(current, {"tool": "adapter__filesystem_set_permissions", "arguments_raw": json.dumps(args),
                                             "_model_visible_tools": worker.tools(current)})
    assert fixed.executed, fixed.error
    assert calls == [("filesystem.set_permissions", args)]
    assert not worker._generic_completion_gate(current)["passed"]
    final_scan(current)
    assert worker._generic_completion_gate(current)["passed"]


def test_final_inventory_certifies_each_mode_including_already_correct_targets():
    current = state()
    final_scan(current)
    assert completion_outcome_issues(current) == []
    assert agent()._generic_completion_gate(current)["passed"]
    # Even when ready, ordinary repairs, inspection and search remain callable.
    assert names(agent(), current) == {"propose_done", "fail_task", "completion_revise"}
    assert current.workflow_progress()["pending_phase"] == "outcomes_verified"


@pytest.mark.parametrize("defect", ["wrong_root", "child_root", "glob", "nonrecursive", "truncated",
                                   "hidden", "depth", "scan_error", "unknown_mode", "wrong_mode", "unknown_coverage"])
def test_partial_or_wrong_evidence_cannot_close_universal_request(defect):
    current = state()
    final_scan(current)
    result = current.events[-1].result["context_hint"]
    if defect in {"wrong_root", "child_root"}:
        result["roots"] = ["/data/elsewhere" if defect == "wrong_root" else "/data/work/nested"]
    elif defect == "glob":
        result["name_patterns"] = ["*.txt"]
    elif defect == "nonrecursive":
        result["recursive"] = False
    elif defect == "truncated":
        result["truncated"] = True
        result["match_count"] = 7
    elif defect == "hidden":
        result["skipped_hidden_count"] = 1
    elif defect == "depth":
        result["depth_limited_directories"] = ["/data/work/deeper"]
    elif defect == "scan_error":
        result["scan_errors"] = [{"path": "/data/work/locked"}]
    elif defect == "unknown_coverage":
        del result["scan_complete"]
    else:
        result["matches"][2]["mode"] = None if defect == "unknown_mode" else "0777"
    assert not agent()._generic_completion_gate(current)["passed"]
    assert "adapter__filesystem_set_permissions" in names(agent(), current)


def test_final_scan_discovers_new_target_and_later_mutation_invalidates_evidence():
    current = state()
    final_scan(current)
    scan = current.events[-1].result["context_hint"]
    scan["matches"].append({"path": "/data/work/new", "kind": "file", "mode": "0600"})
    scan.update(match_count=4, returned_count=4)
    assert any(i["target"] == {"path": "/data/work/new"} for i in completion_outcome_issues(current))
    scan["matches"].pop()
    scan.update(match_count=3, returned_count=3)
    current.events.append(event(4, "command.run", {"command": "touch /data/work/new"}, {"returncode": 0}))
    assert not agent()._generic_completion_gate(current)["passed"]


def test_fresh_wrong_mode_allows_one_identical_retry_after_native_contradiction():
    current = state()
    final_scan(current, modes=("0755", "0640", "0777"))
    assert outcome_retry_allowed(current, "os", "filesystem.set_permissions", {"path": "/data/work/one", "mode": "640"}, 2)
    assert not outcome_retry_allowed(current, "os", "filesystem.set_permissions", {"path": "/data/work/one", "mode": "777"}, 2)
    assert not outcome_retry_allowed(current, "os", "filesystem.set_permissions", {"path": "/data/work/one", "mode": "640"}, 3)


@pytest.mark.parametrize("text", ["The remaining two files still need to be processed.",
                                  "Two remaining files require permission change.",
                                  "There are pending targets that need to be updated.", "还有两个文件需要修改权限。"])
def test_explicit_admission_blocks_success(text):
    assert completion_claim_contradictions({"reason": text, "evidence": "one target verified"})


def test_negative_pending_statement_does_not_block_success():
    assert completion_claim_contradictions({"reason": "No remaining files require changes.", "evidence": "all modes read back"}) == []


def test_successful_final_review_commits_without_another_audit_or_repair():
    current = state()
    final_scan(current)
    current.defer_terminal_audit = True
    worker = agent()
    result = worker.execute_proposal(current, {
        "tool": "propose_done", "arguments_raw": json.dumps({
            "reason": "Every regular file has the requested mode.",
            "evidence": ["Final complete inventory reports 0640 for every file."],
        }), "_model_visible_tools": worker.tools(current),
    })
    assert result.executed, result.error
    assert current.done
    assert current.pending_terminal is None
    assert mark_tool_result_for_audit(current, result)["status"] == "not_required"
    assert current.pending_model_audit is None
    assert not result.audit_required
    assert worker.tools(current) == []


def test_find_reports_actual_modes_and_limited_scan_coverage(tmp_path):
    (tmp_path / "visible").write_text("test")
    (tmp_path / "visible").chmod(0o600)
    (tmp_path / ".hidden").write_text("hidden")
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "deep").write_text("deep")
    worker = object.__new__(OSActions)
    args = {"roots": [str(tmp_path)], "name_patterns": ["*"], "kind": "file", "recursive": True}
    scan = worker.find_files(args, 10)
    assert scan["scan_complete"] is False and scan["skipped_hidden_count"] == 1
    scan = worker.find_files({**args, "include_hidden": True, "max_depth": 1}, 10)
    assert scan["scan_complete"] is False and scan["depth_limited_directories"]
    scan = worker.find_files({**args, "include_hidden": True}, 10)
    assert scan["scan_complete"] is True and scan["returned_count"] == 3
    assert next(m for m in scan["matches"] if m["name"] == "visible")["mode"] == "0600"
    body = {"status": "ok", "result": scan}
    hint = adapter_context_hint("os", "filesystem.find", body)
    assert hint["scan_complete"] and hint["roots"] == [str(tmp_path)]
    assert next(m for m in hint["matches"] if m["name"] == "visible")["mode"] == "0600"
    compact_adapter_body(body)


def test_symlink_cannot_hide_or_certify_a_regular_target(tmp_path):
    path = tmp_path / "actual"
    path.write_text("actual")
    (tmp_path / "z-link").symlink_to(path)
    scan = object.__new__(OSActions).find_files({"roots": [str(tmp_path)], "name_patterns": ["*"]}, 10)
    assert len(scan["matches"]) == 2
    assert len({m["path"] for m in scan["matches"]}) == 2
    assert sum(m["is_symlink"] for m in scan["matches"]) == 1


def test_failed_dispatched_mutation_demands_new_inventory():
    current = state()
    final_scan(current)
    failed = event(4, "filesystem.set_permissions", {"path": "/data/work/one", "mode": "777"}, {})
    failed.executed = False
    failed.error = {"detail": "verification failed after dispatch"}
    current.events.append(failed)
    assert any(i["code"] == "permissions.final_state_unverified" for i in completion_outcome_issues(current))


def test_nonpermission_ready_task_waits_for_final_review_instead_of_repair():
    current = state()
    current.instruction = "Set the clipboard text to hello."
    current.events = [event(1, "clipboard.set", {"text": "hello"}, {"verification_passed": True})]
    worker = agent()
    assert worker._generic_completion_gate(current)["passed"]
    assert names(worker, current) == {"propose_done", "fail_task", "completion_revise"}
