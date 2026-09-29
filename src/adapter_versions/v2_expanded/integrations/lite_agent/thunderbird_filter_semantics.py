"""Task-independent routing semantics for Thunderbird message filters."""

from __future__ import annotations

import re


FILTER_NOUN_RE = re.compile(r"(?i)\b(?:filter|filters|rule|rules)\b")
FILTER_ACTION_RE = re.compile(
    r"(?i)\b(?:auto|automatic|automatically|configure|create|forward|move|route|routing|set\s+up)\b"
)
MESSAGE_RE = re.compile(r"(?i)\b(?:email|emails|mail|message|messages|inbox)\b")
SUBFOLDER_APPLICATION_RE = re.compile(r"(?i)\bsubfolders?\b")
EXPLICIT_RULE_RE = re.compile(
    r"(?i)\b(?:condition|criteria|contains|matches|subject|sender|recipient|"
    r"forward|move|route|routing)\b"
)


def requests_filter_configuration(domain: str, instruction: str) -> bool:
    """Return whether an instruction explicitly requests a mail-filter mutation."""
    # Applying existing filters to subfolders changes a global preference; it
    # does not define a filter rule unless criteria or a concrete rule action
    # is also supplied.
    if SUBFOLDER_APPLICATION_RE.search(instruction) and not EXPLICIT_RULE_RE.search(
        instruction
    ):
        return False
    return bool(
        domain == "thunderbird"
        and FILTER_NOUN_RE.search(instruction)
        and FILTER_ACTION_RE.search(instruction)
        and MESSAGE_RE.search(instruction)
    )


__all__ = ["requests_filter_configuration"]
