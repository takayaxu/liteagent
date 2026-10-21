"""Strict generic contracts for writing one live Impress semantic text role."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


TEXT_ACTION = "slide.set_role_text"
FORMAT_ACTION = "slide.format_text_roles"
_FORMAT_FIELDS = frozenset(
    {
        "color",
        "font_size",
        "font_name",
        "bold",
        "italic",
        "underline",
        "strike",
        "alignment",
    }
)
_ORDINAL_SLIDES = {
    "first": 0,
    "second": 1,
    "third": 2,
    "fourth": 3,
    "fifth": 4,
    "sixth": 5,
    "seventh": 6,
    "eighth": 7,
    "ninth": 8,
    "tenth": 9,
}
_QUOTED = r'["“]([^"”\r\n]+)["”]'


@dataclass(frozen=True)
class RoleTextUpdateIntent:
    slide: int
    role: str
    text: str
    formatting: dict[str, Any]


def _target_slide(instruction: str) -> int | None:
    numeric = re.search(r"(?i)\b(?:slide|page)\s+(\d+)\b", instruction)
    if numeric is not None:
        number = int(numeric.group(1))
        return number - 1 if number >= 1 else None
    ordinal = re.search(
        r"(?i)\b(" + "|".join(_ORDINAL_SLIDES) + r")\s+(?:slide|page)\b",
        instruction,
    )
    return _ORDINAL_SLIDES[ordinal.group(1).casefold()] if ordinal else None


def _title_text(instruction: str) -> str | None:
    patterns = (
        rf"(?is)\btitle\b\s*(?:to|as)?\s*[,=:]?\s*{_QUOTED}",
        rf"(?is)\b(?:give|insert|add|set|replace|write|put)\b"
        rf".{{0,80}}?{_QUOTED}\s*(?:as\s+)?(?:the\s+)?title\b",
    )
    values = {
        match.group(1).strip()
        for pattern in patterns
        for match in re.finditer(pattern, instruction)
        if match.group(1).strip()
    }
    return values.pop() if len(values) == 1 else None


def _font_name(instruction: str) -> str | None:
    match = re.search(
        rf"(?is)\bfont(?:\s+(?:style|family|name))?\b\s*"
        rf"(?:to|as|is|:)?\s*{_QUOTED}",
        instruction,
    )
    return match.group(1).strip() if match and match.group(1).strip() else None


def parse_role_text_update_intent(
    instruction: str,
) -> RoleTextUpdateIntent | None:
    """Parse a reusable title-writing request without selecting a live shape."""
    if not re.search(r"(?i)\btitle\b", instruction) or not re.search(
        r"(?i)\b(?:give|insert|add|set|replace|write|put|change|update)\b",
        instruction,
    ):
        return None
    slide = _target_slide(instruction)
    text = _title_text(instruction)
    if slide is None or text is None:
        return None

    formatting: dict[str, Any] = {}
    alignment = re.search(
        r"(?i)\b(left|right|center)(?:-|\s*)align(?:ed|ment)?\b", instruction
    )
    if alignment is not None:
        formatting["alignment"] = alignment.group(1).casefold()
    font_name = _font_name(instruction)
    if font_name is not None:
        formatting["font_name"] = font_name
    return RoleTextUpdateIntent(
        slide=slide,
        role="title",
        text=text,
        formatting=formatting,
    )


def _text_arguments_match_intent(
    arguments: dict[str, Any], intent: RoleTextUpdateIntent
) -> bool:
    expected = {
        "slide": intent.slide,
        "role": intent.role,
        "text": intent.text,
    }
    return arguments == expected


def _format_arguments_match_intent(
    arguments: dict[str, Any], intent: RoleTextUpdateIntent
) -> bool:
    return bool(intent.formatting) and arguments == {
        "slide": intent.slide,
        "roles": [intent.role],
        **intent.formatting,
    }


def role_text_update_argument_contract_errors(
    state: Any, action: str, arguments: dict[str, Any]
) -> list[str]:
    """Validate model-selected fields without filling or rewriting any value."""
    intent = parse_role_text_update_intent(str(state.instruction))
    if intent is None or action not in {TEXT_ACTION, FORMAT_ACTION}:
        return []
    if action == TEXT_ACTION:
        if _text_arguments_match_intent(arguments, intent):
            return []
        return [
            "slide.set_role_text must contain only the instruction-stated zero-based "
            "slide, semantic role, and exact replacement text; formatting belongs in a "
            "separate slide.format_text_roles call"
        ]
    if not intent.formatting or _format_arguments_match_intent(arguments, intent):
        return []
    return [
        "slide.format_text_roles must contain the instruction-stated zero-based slide, "
        "the replaced semantic role in roles, and every explicitly requested formatting "
        f"field with no extras: {sorted(intent.formatting)}"
    ]


def _mappings(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _mappings(child)


def _text_adapter_confirmed(event: Any, intent: RoleTextUpdateIntent) -> bool:
    arguments = event.proposed.get("arguments")
    if not isinstance(arguments, dict) or not _text_arguments_match_intent(
        arguments, intent
    ):
        return False
    return any(
        candidate.get("slide") == intent.slide
        and candidate.get("requested_role") == intent.role
        and candidate.get("resolved_role") == intent.role
        and candidate.get("text") == intent.text
        and isinstance(candidate.get("path"), list)
        for candidate in _mappings(event.result)
    )


def _format_adapter_confirmed(event: Any, intent: RoleTextUpdateIntent) -> bool:
    arguments = event.proposed.get("arguments")
    if not isinstance(arguments, dict) or not _format_arguments_match_intent(
        arguments, intent
    ):
        return False
    mappings = list(_mappings(event.result))
    return (
        any(candidate.get("slide") == intent.slide for candidate in mappings)
        and any(
            candidate.get("requested_roles") == [intent.role] for candidate in mappings
        )
        and any(
            candidate.get("role") == intent.role
            and isinstance(candidate.get("path"), list)
            and isinstance(candidate.get("properties"), dict)
            and candidate["properties"]
            for candidate in mappings
        )
    )


def role_text_update_requirement_errors(state: Any) -> list[str]:
    """Require an Adapter-confirmed model-selected role-text mutation."""
    intent = parse_role_text_update_intent(str(state.instruction))
    if intent is None:
        return []
    errors = []
    if not any(
        _text_adapter_confirmed(event, intent)
        for event in state.successful_action_events(TEXT_ACTION)
    ):
        errors.append(
            "slide.set_role_text lacks Adapter-confirmed coverage for the requested "
            "semantic role and exact replacement text"
        )
    if intent.formatting and not any(
        _format_adapter_confirmed(event, intent)
        for event in state.successful_action_events(FORMAT_ACTION)
    ):
        errors.append(
            "slide.format_text_roles lacks Adapter-confirmed coverage for the formatting "
            "explicitly requested with the semantic-role text replacement"
        )
    return errors


def stage_actions(state: Any, actions: list[str]) -> list[str]:
    """Expose only the pending public action; never derive its arguments."""
    intent = parse_role_text_update_intent(str(state.instruction))
    if intent is None:
        return actions
    if not state.successful_action_events("presentation.inspect"):
        return [action for action in actions if action == "presentation.inspect"]
    if not any(
        _text_adapter_confirmed(event, intent)
        for event in state.successful_action_events(TEXT_ACTION)
    ):
        return [action for action in actions if action == TEXT_ACTION]
    if intent.formatting and not any(
        _format_adapter_confirmed(event, intent)
        for event in state.successful_action_events(FORMAT_ACTION)
    ):
        return [action for action in actions if action == FORMAT_ACTION]
    return actions


__all__ = [
    "FORMAT_ACTION",
    "RoleTextUpdateIntent",
    "TEXT_ACTION",
    "parse_role_text_update_intent",
    "role_text_update_argument_contract_errors",
    "role_text_update_requirement_errors",
    "stage_actions",
]
