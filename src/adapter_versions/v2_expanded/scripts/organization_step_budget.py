"""Runner-owned step estimates from an authoritative organization inventory."""

from __future__ import annotations

from typing import Any


def estimate_organization_step_budget(
    state: Any, *, used_steps: int, initial_limit: int, hard_limit: int
) -> dict[str, Any] | None:
    """Estimate once after complete discovery, without choosing any disposition.

    Each unresolved source gets three phase steps and one retry/extra-read step.
    Four final steps cover completion and review with a small additional margin.
    This is a heuristic, never permission to exceed the preconfigured hard cap.
    RuntimeState supplies the existing deduplicated, destination-filtered ledger;
    nested reader listings cannot introduce additional source objects here.
    """
    if not state.filesystem_move_requested():
        return None
    marker = state.filesystem_observation_state()
    if not isinstance(marker, dict) or marker.get("complete") is not True:
        return None
    progress = state.filesystem_organization_progress()
    source_count = len(progress["objects"])
    pending_count = len(progress["pending_objects"])
    estimated_steps = used_steps + pending_count * 4 + 4
    return {
        "basis": "complete_observed_source_inventory",
        "observed_at_step": used_steps,
        "source_count": source_count,
        "pending_source_count": pending_count,
        "phase_steps_per_source": 3,
        "retry_steps_per_source": 1,
        "completion_reserve_steps": 4,
        "estimated_steps": estimated_steps,
        "effective_limit": min(hard_limit, max(initial_limit, estimated_steps)),
        "estimate_exceeds_hard_limit": estimated_steps > hard_limit,
    }
