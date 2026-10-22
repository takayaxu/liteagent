"""Runtime event and state model assembled from focused evidence mixins."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .state_core import RuntimeStateCoreMixin
from .state_calc import CalcStateMixin
from .state_impress import ImpressStateMixin


@dataclass
class ExecutionEvent:
    step: int
    timestamp_utc: str
    proposed: dict[str, Any]
    parsed: bool = False
    validated: bool = False
    executed: bool = False
    result: Any = None
    error: Any = None
    duration_seconds: float = 0.0
    screenshot_before: str | None = None
    screenshot_after: str | None = None
    # Every Tool result is handed back to Qwen before the next decision.  These
    # fields make that handoff auditable without adding model content to the
    # event or changing the model-selected payload.
    audit_required: bool = False
    audit_completed: bool = False
    audit_tool: str | None = None
    local_step: int | None = None
    retry: int = 0


@dataclass
class RuntimeState(RuntimeStateCoreMixin, CalcStateMixin, ImpressStateMixin):
    task_id: str
    domain: str
    instruction: str
    recommended_actions: list[str] = field(default_factory=list)
    working_directory: str | None = None
    expanded_actions: list[str] = field(default_factory=list)
    events: list[ExecutionEvent] = field(default_factory=list)
    done: bool = False
    failed: bool = False
    completion_rejections: int = 0
    runner_replans_requested: int = 0
    pending_runner_replan: dict[str, Any] | None = None
    # Local turn/retry counters are separate from the immutable event step.
    # A same-VM soft restart resets ``local_step`` only; ``events`` remains the
    # complete episode ledger and ``retry`` remains bounded by the Runner.
    local_step: int = 1
    retry: int = 0
    soft_restart_count: int = 0
    recovery_context: dict[str, Any] | None = None
    # A deterministic, one-shot mutation repair produced after a structured
    # validation reject. The model can only confirm its id; the runner owns
    # the corrected arguments and consumes this contract on success.
    repair_contract: dict[str, Any] | None = None
    # A soft-restart handoff remains model-visible for a small bounded number
    # of valid follow-up turns.  These counters are runner state only; they are
    # never serialized into the model-facing recovery projection.
    recovery_projection_turns_remaining: int = 0
    recovery_projection_initial_audit_pending: bool = False
    recovery_history: list[dict[str, Any]] = field(default_factory=list)
    pending_model_audit: dict[str, Any] | None = None
    last_model_audit: dict[str, Any] | None = None
    # Enables action/GUI audit evidence and the legacy failure acknowledgement.
    # Successful completion always commits immediately after the final gate.
    defer_terminal_audit: bool = False
    pending_terminal: dict[str, Any] | None = None
    terminal_confirmation: bool = False
    # Authoritative per-object organization ledger. A source advances only
    # after classification plus either a committed move or an explicit retain.
    filesystem_organization_ledger: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    filesystem_organization_active_path: str | None = None
