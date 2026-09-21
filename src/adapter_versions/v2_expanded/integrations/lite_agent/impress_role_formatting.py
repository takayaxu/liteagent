"""Strict generic contracts for semantic role formatting across multiple slides."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .impress_colors import IMPRESS_NAMED_COLORS, normalize_impress_color


ACTION = "slides.format_text_roles"
SINGLE_ACTION = "slide.format_text_roles"
ROLE_ACTIONS = (ACTION, SINGLE_ACTION)
_STYLE_FIELDS = frozenset({"color", "bold", "italic", "underline", "strike"})
_CLAUSE_BOUNDARY_RE = re.compile(
    r"(?i)(?:[.!?;]+\s*|\b(?:also|additionally|afterwards|then)\b[,:]?\s*)"
)


@dataclass(frozen=True)
class MultiSlideRoleFormatIntent:
    slides: tuple[int, ...]
    roles: tuple[str, ...]
    properties: dict[str, Any]


def _shape_text(shape: dict[str, Any]) -> str:
    lines = shape.get("lines")
    if isinstance(lines, list):
        text = "\n".join(str(line) for line in lines).strip()
        if text:
            return text
    text = shape.get("text")
    return text.strip() if isinstance(text, str) else ""


def _visual_title_shape(slide: dict[str, Any]) -> dict[str, Any] | None:
    values = slide.get("text_shapes")
    if not isinstance(values, list):
        values = slide.get("all_shapes")
    if not isinstance(values, list):
        return None
    candidates = []
    for shape in values:
        if not isinstance(shape, dict) or not isinstance(shape.get("path"), list):
            continue
        if not _shape_text(shape):
            continue
        kind = str(shape.get("kind", "")).casefold()
        style = shape.get("text_style")
        font_size = style.get("font_size") if isinstance(style, dict) else None
        y, height = shape.get("y"), shape.get("height")
        if not isinstance(font_size, (int, float)) or isinstance(font_size, bool):
            continue
        if not isinstance(y, (int, float)) or not isinstance(height, (int, float)):
            continue
        if kind.endswith(".titletextshape") or kind.endswith("titletextshape"):
            return shape
        candidates.append((shape, float(font_size), float(y) + float(height) / 2))
    if not candidates:
        return None
    slide_height = slide.get("height")
    if isinstance(slide_height, (int, float)) and not isinstance(slide_height, bool):
        candidates = [item for item in candidates if item[2] <= float(slide_height) / 2]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[1], tuple(item[0]["path"])))
    if len(candidates) > 1 and (
        candidates[0][1] == candidates[1][1]
        or candidates[0][1] < candidates[1][1] * 1.5
    ):
        return None
    return candidates[0][0]


def _visual_title_role_format_satisfied(
    state: Any, intent: MultiSlideRoleFormatIntent
) -> bool:
    for action in ROLE_ACTIONS:
        for event in state.successful_action_events(action):
            arguments = event.proposed.get("arguments")
            if not isinstance(arguments, dict) or not _arguments_match_intent(
                arguments, intent
            ):
                continue
            if adapter_confirmed_role_slides(event, intent.roles) >= set(intent.slides):
                return True
    return False


def multislide_visual_title_fallback_plan(state: Any) -> dict[str, Any] | None:
    """Build an atomic plan when imported slides lack native title roles."""
    intent = parse_multislide_role_format_intent(str(state.instruction))
    if intent is None or not state.successful_action_events("presentation.inspect"):
        return None
    initial = state.initial_presentation_context_hint()
    slides = initial.get("slides") if isinstance(initial, dict) else None
    if not isinstance(slides, list):
        return None
    targets = []
    for slide_index in intent.slides:
        slide = next(
            (item for item in slides if isinstance(item, dict) and item.get("slide") == slide_index),
            None,
        )
        if not isinstance(slide, dict):
            return None
        shape = _visual_title_shape(slide)
        if shape is None:
            return None
        targets.append(
            {
                "action": "shape.format_text",
                "arguments": {
                    "slide": slide_index,
                    "selector": {"path": list(shape["path"])},
                    **intent.properties,
                },
            }
        )
    has_native_titles = all(
        any(
            isinstance(shape, dict)
            and str(shape.get("kind", "")).casefold().endswith("titletextshape")
            for shape in (slide.get("text_shapes") or slide.get("all_shapes") or [])
        )
        for slide in slides
        if isinstance(slide, dict) and slide.get("slide") in intent.slides
    )
    if has_native_titles:
        return None
    return {"intent": intent, "steps": targets}


def next_multislide_visual_title_action(state: Any) -> dict[str, Any] | None:
    plan = multislide_visual_title_fallback_plan(state)
    if plan is None:
        return None
    intent = plan["intent"]
    for action in ROLE_ACTIONS:
        for event in state.successful_action_events(action):
            arguments = event.proposed.get("arguments")
            if isinstance(arguments, dict) and _arguments_match_intent(
                arguments, intent
            ):
                return None
    successful = state.successful_action_events("shape.format_text")
    for step in plan["steps"]:
        expected = dict(step["arguments"])
        if "color" in expected:
            expected["color"] = normalize_impress_color(expected["color"])
        covered = False
        for event in successful:
            actual = event.proposed.get("arguments")
            if not isinstance(actual, dict):
                continue
            actual = dict(actual)
            if "color" in actual:
                actual["color"] = normalize_impress_color(actual["color"])
            if actual == expected:
                covered = True
                break
        if not covered:
            return step
    return None


def multislide_visual_title_argument_contract_errors(
    state: Any, action: str, arguments: dict[str, Any]
) -> list[str]:
    if action != "shape.format_text":
        return []
    step = next_multislide_visual_title_action(state)
    if step is None:
        return []
    expected = dict(step["arguments"])
    actual = dict(arguments)
    for values in (expected, actual):
        if "color" in values:
            values["color"] = normalize_impress_color(values["color"])
    if actual != expected:
        return [
            "imported-slide title formatting must match the next observed visual-title "
            f"shape step: {step!r}"
        ]
    return []


def _listed_slides(text: str) -> tuple[int, ...]:
    values: set[int] = set()
    token_re = re.compile(r"(?i)\s*(\d+|,|&|-|\band\b|\bto\b|\bthrough\b)")
    for term in re.finditer(r"(?i)\b(?:slides?|pages?)\b", text):
        cursor = term.end()
        tokens: list[str] = []
        while match := token_re.match(text, cursor):
            tokens.append(match.group(1))
            cursor = match.end()
        spec = " ".join(tokens)
        if not spec:
            continue
        values.update(int(value) for value in re.findall(r"\d+", spec))
        for start, end in re.findall(r"(?i)(\d+)\s*(?:-|to|through)\s*(\d+)", spec):
            first, last = int(start), int(end)
            if first >= 1 and last >= first:
                values.update(range(first, last + 1))
    return tuple(value - 1 for value in sorted(values) if value >= 1)


def _title_format_scope(instruction: str) -> str:
    """Keep unrelated operation clauses from contributing slide references."""
    clauses = [part.strip() for part in _CLAUSE_BOUNDARY_RE.split(instruction)]
    candidates = [
        clause
        for clause in clauses
        if re.search(r"(?i)\b(?:titles?|headings?)\b", clause)
        and re.search(r"(?i)\b(?:slides?|pages?)\b", clause)
    ]
    return candidates[0] if len(candidates) == 1 else instruction


def _instruction_color(text: str) -> str | None:
    tokens = set(re.findall(r"(?i)#[0-9a-f]{6}\b", text))
    for name in sorted(IMPRESS_NAMED_COLORS, key=len, reverse=True):
        if re.search(rf"(?i)(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", text):
            tokens.add(name)
    normalized = {
        color
        for token in tokens
        if (color := normalize_impress_color(token)) is not None
    }
    return normalized.pop() if len(normalized) == 1 else None


def _boolean_style(text: str, term: str) -> bool | None:
    if not re.search(rf"(?i)\b{term}\w*\b", text):
        return None
    disabled = re.search(
        rf"(?is)\b(?:clear|disable|not|no|remove|without)\b.{{0,32}}\b{term}\w*\b|"
        rf"\b{term}\w*\b.{{0,24}}\b(?:off|false)\b",
        text,
    )
    return disabled is None


def parse_multislide_role_format_intent(
    instruction: str,
) -> MultiSlideRoleFormatIntent | None:
    """Parse uniform title formatting on an arbitrary explicit slide list."""
    # Composite title-range plus personal-information cleanup has its own
    # observation-derived atomic plan. Do not reinterpret that request as a
    # semantic role-format operation, which would impose an unrelated
    # slides.format_text_roles completion requirement.
    if re.search(
        r"(?is)\b(?:delete|remove|clear|erase)\b.{0,100}\bpersonal\s+information\b",
        instruction,
    ):
        return None
    scope = _title_format_scope(instruction)
    slides = _listed_slides(scope)
    if len(slides) < 2 or not re.search(r"(?i)\b(?:titles?|headings?)\b", scope):
        return None
    if re.search(r"(?i)\b(?:body|content|tables?|text\s*boxes?|textboxes?)\b", scope):
        return None

    properties: dict[str, Any] = {}
    color = _instruction_color(scope)
    if color is not None:
        properties["color"] = color
    for field, term in (
        ("bold", "bold"),
        ("italic", "italic"),
        ("underline", "underlin"),
        ("strike", "strik"),
    ):
        value = _boolean_style(scope, term)
        if value is not None:
            properties[field] = value
    if not properties:
        return None
    return MultiSlideRoleFormatIntent(
        slides=slides,
        roles=("title",),
        properties=properties,
    )


def action_slide_indices(arguments: dict[str, Any]) -> tuple[int, ...] | None:
    has_slide = "slide" in arguments
    has_slides = "slides" in arguments
    if has_slide == has_slides:
        return None
    values = [arguments.get("slide")] if has_slide else arguments.get("slides")
    if (
        not isinstance(values, list)
        or not values
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        )
        or len(values) != len(set(values))
    ):
        return None
    return tuple(values)


def _arguments_match_intent(
    arguments: dict[str, Any], intent: MultiSlideRoleFormatIntent
) -> bool:
    slides = action_slide_indices(arguments)
    if slides is None or not set(slides).issubset(intent.slides):
        return False
    roles = arguments.get("roles")
    if roles != list(intent.roles) or "overrides" in arguments:
        return False
    supplied = {key: arguments[key] for key in _STYLE_FIELDS if key in arguments}
    if set(supplied) != set(intent.properties):
        return False
    for key, expected in intent.properties.items():
        actual = supplied[key]
        if key == "color":
            if normalize_impress_color(actual) != expected:
                return False
        elif actual is not expected:
            return False
    return True


def multislide_role_argument_contract_errors(
    state: Any, action: str, arguments: dict[str, Any]
) -> list[str]:
    """Validate model-selected role-format arguments without modifying them."""
    intent = parse_multislide_role_format_intent(str(state.instruction))
    if intent is None or action not in ROLE_ACTIONS:
        return []
    if action == ACTION and ("slides" not in arguments or "slide" in arguments):
        return [
            "slides.format_text_roles requires a unique nonempty zero-based slides array"
        ]
    if action == SINGLE_ACTION and ("slide" not in arguments or "slides" in arguments):
        return ["slide.format_text_roles requires one valid zero-based slide"]
    slides = action_slide_indices(arguments)
    if slides is None:
        return [f"{action} has an invalid zero-based slide target"]
    if not set(slides).issubset(intent.slides):
        return [
            f"{action} may target only the zero-based slides explicitly "
            f"requested by the instruction: {list(intent.slides)}"
        ]
    if arguments.get("roles") != list(intent.roles):
        return ["this request targets the semantic title role; pass roles=['title']"]
    if "overrides" in arguments:
        return ["uniform multi-slide title formatting does not require overrides"]
    supplied = {key: arguments[key] for key in _STYLE_FIELDS if key in arguments}
    if set(supplied) != set(intent.properties):
        return [
            "the role-format call must contain every and only the shared style properties "
            f"requested by the instruction: {sorted(intent.properties)}"
        ]
    for key, expected in intent.properties.items():
        actual = supplied[key]
        matches = (
            normalize_impress_color(actual) == expected
            if key == "color"
            else actual is expected
        )
        if not matches:
            return [f"the model-selected {key} value does not match the instruction"]
    return []


def _mappings(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _mappings(child)


def adapter_confirmed_role_slides(
    event: Any, expected_roles: tuple[str, ...]
) -> set[int]:
    """Return slides whose Adapter result confirms a nonempty semantic-role rule."""
    arguments = event.proposed.get("arguments")
    if not isinstance(arguments, dict):
        return set()
    requested = action_slide_indices(arguments)
    if requested is None:
        return set()
    expected = set(expected_roles)
    confirmed: set[int] = set()
    for candidate in _mappings(event.result):
        slide = candidate.get("slide")
        rules = candidate.get("rules")
        if (
            isinstance(slide, bool)
            or not isinstance(slide, int)
            or slide not in requested
            or not isinstance(rules, list)
        ):
            continue
        if any(
            isinstance(rule, dict)
            and set(rule.get("normalized_roles", [])) == expected
            and isinstance(rule.get("formatted"), list)
            and bool(rule["formatted"])
            for rule in rules
        ):
            confirmed.add(slide)
    return confirmed


def multislide_role_requirement_errors(state: Any) -> list[str]:
    """Require Adapter-confirmed coverage for every instruction-named slide."""
    intent = parse_multislide_role_format_intent(str(state.instruction))
    if intent is None:
        return []
    fallback = multislide_visual_title_fallback_plan(state)
    if fallback is not None:
        for action in ROLE_ACTIONS:
            for event in state.successful_action_events(action):
                arguments = event.proposed.get("arguments")
                if not isinstance(arguments, dict) or not _arguments_match_intent(
                    arguments, intent
                ):
                    continue
                return []
        missing = [
            step
            for step in fallback["steps"]
            if not any(
                event.proposed.get("arguments") == step["arguments"]
                for event in state.successful_action_events("shape.format_text")
            )
        ]
        if missing:
            return [
                "observation-derived visual-title formatting lacks successful "
                f"shape.format_text coverage for {len(missing)} target slide(s)"
            ]
        return []
    covered: set[int] = set()
    for action in ROLE_ACTIONS:
        for event in state.successful_action_events(action):
            arguments = event.proposed.get("arguments")
            if not isinstance(arguments, dict) or not _arguments_match_intent(
                arguments, intent
            ):
                continue
            covered.update(adapter_confirmed_role_slides(event, intent.roles))
    missing = sorted(set(intent.slides).difference(covered))
    if not missing:
        return []
    return [
        "slides.format_text_roles or per-slide role calls lack Adapter-confirmed "
        "title-format coverage for "
        f"zero-based slides {missing}; the complete requested set is {list(intent.slides)}"
    ]


__all__ = [
    "ACTION",
    "ROLE_ACTIONS",
    "SINGLE_ACTION",
    "MultiSlideRoleFormatIntent",
    "action_slide_indices",
    "adapter_confirmed_role_slides",
    "multislide_role_argument_contract_errors",
    "multislide_role_requirement_errors",
    "multislide_visual_title_argument_contract_errors",
    "multislide_visual_title_fallback_plan",
    "next_multislide_visual_title_action",
    "parse_multislide_role_format_intent",
]
