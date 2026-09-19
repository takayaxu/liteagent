"""Fail-closed mutation scope for strict semantic tool search."""

from __future__ import annotations

from collections.abc import Iterable

from .completion_policy import action_is_read_only


def scope_semantic_search_actions(
    actions: Iterable[str],
    semantic_actions: Iterable[str],
    *,
    strict_generic: bool,
) -> list[str]:
    """Keep declared mutations, saving and read-only observations in strict search.

    A nonempty semantic action set is already the Runtime's public description
    of the instruction's required operations. Search may help the model find
    those actions or gather more state. Cell writing may also use the public
    fill operation without making that implementation choice mandatory.
    Saving current work remains discoverable without becoming a required action.
    """
    candidates = list(dict.fromkeys(actions))
    allowed_mutations = set(semantic_actions)
    if not strict_generic or not allowed_mutations:
        return candidates
    if allowed_mutations.intersection({"range.write", "cells.set_formulas"}):
        allowed_mutations.add("range.fill_down")
    return [
        action
        for action in candidates
        if action in allowed_mutations
        or action_is_read_only(action)
        or action.endswith(".save")
    ]


__all__ = ["scope_semantic_search_actions"]
