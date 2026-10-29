from __future__ import annotations

import json
import re
import time
from collections import deque
from copy import deepcopy
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from .atomic_tool_surface import atomic_provider_surface, restore_adapter_arguments
from openai import OpenAI

from .qwen_pivot_schema import lower_pivot_schemas
from .qwen_shape_format_schema import lower_shape_format_schemas
from .reasoning import (
    SUPPORTED_REASONING_EFFORTS,
    SUPPORTED_REASONING_MODES,
    explicit_effective_reasoning_mode,
    observed_reasoning_mode,
)


_SCHEMA_HINT_MAX = 8
_SCHEMA_HINT_ITEM_MAX = 180
# The Runner owns bounded retries and recomputes the remaining episode
# deadline before each attempt.  OpenAI's implicit retries would otherwise
# keep an HTTP request alive after that deadline and hide the true attempt
# count in the episode ledger.
MODEL_SDK_MAX_RETRIES = 0
QWEN_TOOL_CALL_END = "\n</function>\n</tool_call>"


def _provider_array_uniqueness(schema: Any) -> Any:
    """Move unsupported generation constraints to text, retaining runtime validation.

    Visit schema positions only: properties named uniqueItems and literal JSON
    in defaults/enums must not be mistaken for schema keywords. The caller
    validates returned arguments against the untouched original tool schema.
    """
    if not isinstance(schema, dict):
        return deepcopy(schema)
    result = deepcopy(schema)
    if isinstance(result.get("uniqueItems"), bool):
        unique = result.pop("uniqueItems")
        if unique:
            hint = "Array items must be unique; duplicate items are rejected before execution."
            description = result.get("description", "")
            result["description"] = f"{description}\n{hint}" if description else hint
    for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
        mapping = result.get(key)
        if isinstance(mapping, dict):
            result[key] = {name: _provider_array_uniqueness(value) for name, value in mapping.items()}
    for key in ("items", "additionalItems", "additionalProperties", "contains",
                "propertyNames", "not", "if", "then", "else",
                "unevaluatedItems", "unevaluatedProperties"):
        child = result.get(key)
        if isinstance(child, dict):
            result[key] = _provider_array_uniqueness(child)
        elif key == "items" and isinstance(child, list):
            result[key] = [_provider_array_uniqueness(item) for item in child]
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        children = result.get(key)
        if isinstance(children, list):
            result[key] = [_provider_array_uniqueness(item) for item in children]
    dependencies = result.get("dependencies")
    if isinstance(dependencies, dict):
        result["dependencies"] = {
            key: _provider_array_uniqueness(value) if isinstance(value, dict) else value
            for key, value in dependencies.items()
        }
    return result


def _qwen_schema_compatible_tools(
    model: str, tools: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Prepare generation schemas for the Qwen3.5 grammar backend.

    The unmodified tool catalog remains authoritative for local validation.
    Pivot intersections must become complete alternatives: XGrammar otherwise
    compiles only the oneOf branch and silently loses required common fields.
    """
    if not re.match(r"^qwen3[.]5(?:-|$)", model, re.I):
        return tools

    compatible = deepcopy(tools)

    for tool in compatible:
        function = tool.get("function", {})
        if "parameters" in function:
            function["parameters"] = _provider_array_uniqueness(function["parameters"])
    return lower_shape_format_schemas(lower_pivot_schemas(compatible))


def _bounded_qwen_empty_tool_constraint(
    model: str, tools: list[dict[str, Any]], tool_call_stop_sequence: str | None,
) -> dict[str, Any] | None:
    """Bound whitespace in Qwen XML bodies for tools with no arguments.

    vLLM's automatic required-tool grammar permits unbounded whitespace in an
    empty XML body. With greedy decoding this can loop on newline tokens while
    its tool parser emits no SSE deltas. Preserve the public schemas and bound
    only syntax whitespace, never string values or reasoning.
    """
    if (
        not re.match(r"^qwen3[.]5(?:-|$)", model, re.I)
        or tool_call_stop_sequence != QWEN_TOOL_CALL_END
    ):
        return None
    tags = []
    has_empty_tool = False
    for tool in tools:
        function = tool["function"]
        schema = function["parameters"]
        empty = (
            schema.get("type") == "object"
            and schema.get("properties") == {}
            and not schema.get("required")
            and schema.get("additionalProperties") is False
        )
        has_empty_tool |= empty
        tags.append({
            "type": "tag",
            "begin": f"<tool_call>\n<function={function['name']}>\n",
            "content": {
                "type": "json_schema", "json_schema": schema,
                "style": "qwen_xml", "any_order": False,
                "max_whitespace_cnt": 1 if empty else None,
            },
            "end": "\n</function>\n</tool_call>",
        })
    if not has_empty_tool:
        return None
    return {
        "type": "structural_tag",
        "format": {
            "type": "triggered_tags", "triggers": ["<tool_call>\n<function="],
            "tags": tags, "at_least_one": True, "stop_after_first": True,
            "excludes": ["<think>", "</think>"],
        },
    }


def _same_served_model(expected: str, returned: Any) -> bool:
    """Accept a provider response that omits only a GGUF quantization suffix."""
    if returned == expected:
        return True
    if not isinstance(returned, str):
        return False
    base = re.sub(r"-Q[2-8](?:_[A-Z0-9]+)+$", "", expected, flags=re.I)
    return base != expected and returned == base


def _stream_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _jsonable(value: Any, *, exclude_none: bool = False) -> Any:
    """Serialize both SDK models and lightweight OpenAI-compatible objects."""
    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json", exclude_none=exclude_none)
        except (AttributeError, TypeError, ValueError):
            pass
    if isinstance(value, dict):
        return {
            key: _jsonable(item, exclude_none=exclude_none)
            for key, item in value.items()
            if not (exclude_none and item is None)
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item, exclude_none=exclude_none) for item in value]
    namespace = getattr(value, "__dict__", None)
    if isinstance(namespace, dict):
        return {
            key: _jsonable(item, exclude_none=exclude_none)
            for key, item in namespace.items()
            if not (exclude_none and item is None)
        }
    return value


class _JsonArgumentProgress:
    """Distinguish JSON syntax whitespace from unchanged string-value bytes.

    This is lexical state only, never parsing, validation or rewriting. Keep
    quote/escape state across chunks so whitespace inside a model-authored
    string (including code indentation) remains meaningful progress.
    """

    def __init__(self) -> None:
        self.in_string = False
        self.escaped = False

    def feed(self, value: str) -> bool:
        progress = False
        for character in value:
            if self.in_string:
                progress = True
                if self.escaped:
                    self.escaped = False
                elif character == "\\":
                    self.escaped = True
                elif character == '"':
                    self.in_string = False
            elif character not in " \t\r\n":
                progress = True
                if character == '"':
                    self.in_string = True
        return progress


class _ReasoningCycleDetector:
    """Conservative liveness guard for exact multi-paragraph reasoning cycles.

    Three verbatim periods of at least 1024 characters are a recoverable
    generation failure, not evidence of task completion. Quoted/code text is
    excluded; a fence without an unambiguous close leaves detection suspended.
    """

    def __init__(self) -> None:
        self.pending = ""
        self.paragraphs: deque[str] = deque(maxlen=36)
        self.fence: str | None = None
        self.quote: str | None = None

    def feed(self, value: str) -> dict[str, int] | None:
        self.pending += value
        while "\n\n" in self.pending:
            paragraph, self.pending = self.pending.split("\n\n", 1)
            if self.quote is not None:
                if re.search(r"(?<!\\)" + re.escape(self.quote) + r"[.,;:!?]?\s*$", paragraph):
                    self.quote = None
                continue
            fences = re.findall(r"(?m)^ {0,3}(`{3,}|~{3,})([^\n]*)", paragraph)
            if fences:
                self.paragraphs.clear()
                for fence, suffix in fences:
                    if self.fence is None:
                        self.fence = fence
                    elif (
                        fence[0] == self.fence[0] and len(fence) >= len(self.fence)
                        and not suffix.strip()
                    ):
                        self.fence = None
                continue
            if self.fence is not None:
                continue
            stripped = paragraph.lstrip()
            if stripped.startswith(('"', "'", "“", "‘")):
                closer = {"“": "”", "‘": "’"}.get(stripped[0], stripped[0])
                if not re.search(r"(?<!\\)" + re.escape(closer) + r"[.,;:!?]?\s*$", stripped[1:]):
                    self.quote = closer
                self.paragraphs.clear()
                continue
            # An inline/ambiguous fence may be quoted code. Fail open until
            # an unambiguous matching closing fence is observed.
            for marker in ("```", "~~~"):
                if marker in paragraph:
                    self.fence = marker
                    self.paragraphs.clear()
                    break
            if self.fence is not None:
                continue
            if (
                stripped.startswith(">")
                or paragraph.startswith(("    ", "\t"))
            ):
                self.paragraphs.clear()
                continue
            self.paragraphs.append(paragraph)
            paragraphs = list(self.paragraphs)
            for width in range(1, len(paragraphs) // 3 + 1):
                period = paragraphs[-width:]
                period_chars = len("\n\n".join(period))
                if period_chars < 1024 or len({p for p in period if p.strip()}) < 2:
                    continue
                if period == paragraphs[-2 * width:-width] == paragraphs[-3 * width:-2 * width]:
                    return {"period_paragraphs": width, "period_chars": period_chars, "repetitions": 3}
        return None


def _aggregate_stream_response(
    response: Any, *, progress_timeout_seconds: float | None = None,
) -> Any:
    """Aggregate streamed Chat Completions deltas into the normal response shape."""
    choices = _stream_value(response, "choices")
    if isinstance(choices, list):
        # Test doubles and providers that ignore stream=True may return a full
        # response. Keep that response unchanged.
        return response
    if not hasattr(response, "__iter__"):
        return response

    model = None
    usage = None
    finish_reason = None
    content: list[str] = []
    reasoning: list[str] = []
    reasoning_content: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    argument_progress: dict[int, _JsonArgumentProgress] = {}
    detectors = {key: _ReasoningCycleDetector() for key in ("reasoning", "reasoning_content")}
    output_started = False
    last_progress = time.monotonic()
    for chunk in response:
        model = _stream_value(chunk, "model", model)
        chunk_usage = _stream_value(chunk, "usage")
        if chunk_usage is not None:
            usage = chunk_usage
        chunk_choices = _stream_value(chunk, "choices", []) or []
        # A valid call/content in this very chunk wins over reasoning deltas.
        # Once output starts, reasoning repetition detection is disabled;
        # semantic inactivity still discards the entire unterminated call.
        output_started |= any(
            _stream_value(_stream_value(choice, "delta"), "content")
            or _stream_value(_stream_value(choice, "delta"), "tool_calls")
            for choice in chunk_choices
        )
        terminal_chunk = any(
            _stream_value(choice, "finish_reason") is not None for choice in chunk_choices
        )
        progress = terminal_chunk
        for choice in chunk_choices:
            delta = _stream_value(choice, "delta")
            progress |= any(
                isinstance(value := _stream_value(delta, key), str) and bool(value)
                for key in ("content", "reasoning", "reasoning_content")
            )
            for call in _stream_value(delta, "tool_calls", []) or []:
                index = _stream_value(call, "index", 0)
                if not isinstance(index, int) or index < 0:
                    index = 0
                function = _stream_value(call, "function")
                name = _stream_value(function, "name")
                arguments = _stream_value(function, "arguments")
                if isinstance(arguments, str):
                    # Always feed every call, even if another delta already
                    # established progress; chunk boundaries may split escapes.
                    detector = argument_progress.setdefault(index, _JsonArgumentProgress())
                    progress |= detector.feed(arguments)
                progress |= isinstance(name, str) and bool(name)
                call_id = _stream_value(call, "id")
                progress |= bool(call_id) and call_id != calls.get(index, {}).get("id")
        now = time.monotonic()
        if progress:
            last_progress = now
        elif (progress_timeout_seconds is not None
              and now - last_progress >= progress_timeout_seconds):
            # Bytes/empty deltas keep HTTP's socket timeout alive, but cannot
            # extend semantic inactivity. Never accept an unterminated call.
            snapshot = {
                "model": model, "finish_reason": None, "client_interrupted": True,
                "no_progress_seconds": now - last_progress,
                "message": {"content": "".join(content) or None,
                            "reasoning": "".join(reasoning) or None,
                            "reasoning_content": "".join(reasoning_content) or None,
                            "tool_calls": []},
                "partial_tool_calls": _jsonable(calls),
            }
            closer = getattr(response, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass
            raise StructuredToolProtocolError(
                "model stream made no semantic progress within the request timeout",
                response_snapshot=snapshot,
            )
        repetition = None
        for choice in chunk_choices:
            finish = _stream_value(choice, "finish_reason")
            if finish is not None:
                finish_reason = finish
            delta = _stream_value(choice, "delta")
            if delta is None:
                continue
            text = _stream_value(delta, "content")
            if isinstance(text, str):
                content.append(text)
            for key, target in (("reasoning", reasoning), ("reasoning_content", reasoning_content)):
                value = _stream_value(delta, key)
                if isinstance(value, str):
                    target.append(value)
                    if not output_started and not terminal_chunk and repetition is None:
                        evidence = detectors[key].feed(value)
                        if evidence is not None:
                            repetition = {"channel": key, **evidence}
            for call in _stream_value(delta, "tool_calls", []) or []:
                index = _stream_value(call, "index", 0)
                if not isinstance(index, int) or index < 0:
                    index = 0
                entry = calls.setdefault(
                    index,
                    {"id": None, "name": "", "arguments": []},
                )
                call_id = _stream_value(call, "id")
                if isinstance(call_id, str):
                    entry["id"] = call_id
                function = _stream_value(call, "function")
                name = _stream_value(function, "name")
                arguments = _stream_value(function, "arguments")
                if isinstance(name, str):
                    entry["name"] += name
                if isinstance(arguments, str):
                    entry["arguments"].append(arguments)
        if repetition is not None:
            snapshot = {
                "model": model,
                "usage": _jsonable(usage),
                "finish_reason": None,
                "client_interrupted": True,
                "repetition": repetition,
                "message": {
                    "content": "".join(content) or None,
                    "reasoning": "".join(reasoning) or None,
                    "reasoning_content": "".join(reasoning_content) or None,
                    "tool_calls": [],
                },
            }
            closer = getattr(response, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass  # Preserve the generation failure if cleanup also fails.
            raise StructuredToolProtocolError(
                "reasoning stream repeated without a tool call", response_snapshot=snapshot,
            )

    tool_calls = [
        SimpleNamespace(
            id=entry["id"],
            function=SimpleNamespace(
                name=entry["name"], arguments="".join(entry["arguments"])
            ),
        )
        for _index, entry in sorted(calls.items())
    ]
    message = SimpleNamespace(
        content="".join(content) or None,
        tool_calls=tool_calls,
        reasoning="".join(reasoning) or None,
        reasoning_content="".join(reasoning_content) or None,
    )
    return SimpleNamespace(
        model=model,
        usage=usage,
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
    )


def _safe_schema_path(path: Any) -> str:
    """Render validator paths without copying model-controlled values."""
    parts: list[str] = []
    for item in path:
        text = str(item)
        if (
            len(text) > 64
            or not text
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz"
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
                for character in text
            )
        ):
            text = "<field>"
        parts.append(text)
    return ".".join(parts) or "<root>"


def _safe_schema_value(value: Any) -> str:
    """Keep schema-authored expectations compact and free of actual arguments."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = repr(value)
    elif isinstance(value, list):
        scalar_values = [
            item for item in value if isinstance(item, (str, int, float, bool))
        ]
        text = "[" + ", ".join(repr(item) for item in scalar_values[:8]) + "]"
    else:
        text = type(value).__name__
    return text[:100]


def _safe_required_fields(schema: Any) -> tuple[str, ...]:
    if not isinstance(schema, dict):
        return ()
    required = schema.get("required")
    if not isinstance(required, list):
        return ()
    return tuple(
        field
        for field in required
        if isinstance(field, str)
        and field
        and len(field) <= 64
        and all(
            character
            in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for character in field
        )
    )


def _required_field_alternatives(
    schema: Any,
    *,
    depth: int = 0,
) -> tuple[tuple[str, ...], ...]:
    """Extract bounded positive field alternatives from a public schema union."""
    if not isinstance(schema, dict) or depth > 3:
        return ()
    base = _safe_required_fields(schema)
    for keyword in ("oneOf", "anyOf"):
        branches = schema.get(keyword)
        if not isinstance(branches, list):
            continue
        alternatives: list[tuple[str, ...]] = []
        for branch in branches[:8]:
            nested = _required_field_alternatives(branch, depth=depth + 1)
            if not nested:
                nested = ((),)
            for fields in nested:
                combined = tuple(dict.fromkeys((*base, *fields)))
                if combined and combined not in alternatives:
                    alternatives.append(combined)
        return tuple(alternatives[:8])
    return (base,) if base else ()


def _undiscriminated_union_alternatives(error: Any) -> tuple[tuple[str, ...], ...]:
    branches = getattr(error, "validator_value", None)
    if not isinstance(branches, list):
        return ()
    for branch in branches:
        if not isinstance(branch, dict):
            return ()
        properties = branch.get("properties")
        if isinstance(properties, dict) and any(
            isinstance(field_schema, dict)
            and ("const" in field_schema or "enum" in field_schema)
            for field_schema in properties.values()
        ):
            return ()
    return _required_field_alternatives({str(error.validator): branches})


def _selected_schema_branch_index(error: Any) -> int | None:
    """Select a union branch only when model arguments uniquely identify it."""
    if getattr(error, "validator", None) not in {"oneOf", "anyOf"}:
        return None
    branches = getattr(error, "validator_value", None)
    instance = getattr(error, "instance", None)
    if (
        not isinstance(branches, list)
        or not branches
        or any(not isinstance(branch, dict) for branch in branches)
    ):
        return None

    candidates = {
        index
        for index, branch in enumerate(branches)
        if "type" not in branch
        or Draft202012Validator({"type": branch["type"]}).is_valid(instance)
    }
    if len(candidates) == 1:
        return next(iter(candidates))
    if not candidates or not isinstance(instance, dict):
        return None

    discriminators_by_branch: dict[int, dict[str, Any]] = {}
    for index in sorted(candidates):
        branch = branches[index]
        properties = branch.get("properties")
        if not isinstance(properties, dict):
            return None
        discriminators_by_branch[index] = {
            field: {
                keyword: field_schema[keyword]
                for keyword in ("const", "enum")
                if keyword in field_schema
            }
            for field, field_schema in properties.items()
            if isinstance(field, str)
            and isinstance(field_schema, dict)
            and ("const" in field_schema or "enum" in field_schema)
        }

    shared_fields = set.intersection(
        *(set(fields) for fields in discriminators_by_branch.values())
    )
    present_fields = sorted(field for field in shared_fields if field in instance)
    if not present_fields:
        return None

    for field in present_fields:
        candidates.intersection_update(
            index
            for index, discriminators in discriminators_by_branch.items()
            if Draft202012Validator(discriminators[field]).is_valid(instance[field])
        )
    if len(candidates) != 1:
        return None
    return next(iter(candidates))


def _actionable_validation_errors(errors: list[Any]) -> list[Any]:
    """Descend only into a uniquely selected public-schema union branch."""
    actionable: list[Any] = []
    for error in errors:
        branch_index = _selected_schema_branch_index(error)
        if branch_index is None:
            actionable.append(error)
            continue
        branch_errors = [
            child
            for child in getattr(error, "context", ())
            if tuple(getattr(child, "relative_schema_path", ()))[:1] == (branch_index,)
        ]
        if not branch_errors:
            actionable.append(error)
            continue
        actionable.extend(_actionable_validation_errors(branch_errors))
    return actionable


def _safe_missing_fields(errors: list[Any]) -> tuple[str, ...]:
    fields: list[str] = []
    for error in errors:
        if getattr(error, "validator", None) != "required":
            continue
        required = getattr(error, "validator_value", None)
        local_instance = getattr(error, "instance", None)
        if not isinstance(required, list):
            continue
        for item in required:
            if (
                not isinstance(item, str)
                or not item
                or len(item) > 64
                or any(
                    character not in "abcdefghijklmnopqrstuvwxyz"
                    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
                    for character in item
                )
                or (isinstance(local_instance, dict) and item in local_instance)
                or item in fields
            ):
                continue
            fields.append(item)
            if len(fields) >= _SCHEMA_HINT_MAX:
                return tuple(fields)
    return tuple(fields)


def _schema_validation_hints(
    errors: list[Any], *, instance: dict[str, Any] | None = None
) -> tuple[str, ...]:
    """Create bounded recovery hints from public schema keywords only.

    The invalid value and jsonschema's full message are intentionally omitted:
    they may contain arbitrary model output or user data.  The next model turn
    only needs the path and the schema rule it must satisfy.
    """
    hints: list[str] = []
    for error in errors:
        path = _safe_schema_path(getattr(error, "absolute_path", ()))
        keyword = str(getattr(error, "validator", "schema"))
        value = getattr(error, "validator_value", None)
        if keyword == "required" and isinstance(value, list):
            local_instance = getattr(error, "instance", instance)
            fields = [
                str(item)
                for item in value
                if isinstance(item, str)
                and (not isinstance(local_instance, dict) or item not in local_instance)
                and item
                and len(item) <= 64
                and all(
                    character in "abcdefghijklmnopqrstuvwxyz"
                    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
                    for character in item
                )
            ]
            detail = "required fields: " + ", ".join(fields[:8])
        elif keyword == "enum":
            detail = "must be one of " + _safe_schema_value(value)
        elif keyword == "type":
            detail = "type must be " + _safe_schema_value(value)
            schema = getattr(error, "schema", None)
            items = schema.get("items") if isinstance(schema, dict) else None
            if (
                value == "array"
                and isinstance(items, dict)
                and items.get("type") == "string"
            ):
                detail += (
                    "; use native JSON array of concise strings; do not "
                    "JSON-encode inside string; do not copy full ledger"
                )
            elif value == "array" and isinstance(items, dict) and "oneOf" in items:
                detail += (
                    "; use a native JSON array; each item must be a concise string or "
                    "compact object copied from a successful tool result"
                )
            elif value == "object":
                detail += (
                    "; use a native JSON object, not a JSON-encoded string; "
                    "escape tabs/newlines inside string values as \\t/\\n"
                )
        elif keyword == "minimum":
            detail = "must be >= " + _safe_schema_value(value)
        elif keyword == "maximum":
            detail = "must be <= " + _safe_schema_value(value)
        elif keyword == "minProperties":
            detail = "must contain at least " + _safe_schema_value(value) + " field(s)"
        elif keyword == "uniqueItems":
            detail = "remove duplicate items; include each item only once"
        elif keyword == "additionalProperties" and value is False:
            detail = "remove fields not declared at this level"
            schema = getattr(error, "schema", None)
            properties = schema.get("properties") if isinstance(schema, dict) else None
            if isinstance(properties, dict):
                detail += "; declared fields: " + _safe_schema_value(list(properties))
        elif keyword in {
            "additionalProperties",
            "minItems",
            "maxItems",
            "minLength",
            "maxLength",
            "pattern",
            "const",
        }:
            detail = keyword
            if value is not None:
                detail += "=" + _safe_schema_value(value)
        elif keyword in {"oneOf", "anyOf"}:
            alternatives = _undiscriminated_union_alternatives(error)
            if alternatives:
                rendered = [" + ".join(fields) for fields in alternatives]
                detail = "provide one allowed field set: " + " OR ".join(rendered)
            elif keyword == "oneOf":
                detail = "must match one allowed schema branch"
            else:
                detail = "must match an allowed schema branch"
        else:
            detail = "schema rule " + keyword[:48]
        hint = f"{path}: {detail}"[:_SCHEMA_HINT_ITEM_MAX]
        if hint not in hints:
            hints.append(hint)
        if len(hints) >= _SCHEMA_HINT_MAX:
            break
    return tuple(hints)


class StructuredToolProtocolError(RuntimeError):
    """A model response cannot be safely represented as one complete tool call.

    The raw response is retained on the exception for the immutable trace, but
    the exception text is deliberately bounded and does not contain arguments.
    This lets the Runner request a compact repair without exposing response
    contents as model-facing guidance or silently rewriting them.
    """

    def __init__(
        self,
        reason: str,
        *,
        response_snapshot: dict[str, Any],
        tool_name: str | None = None,
        missing_fields: tuple[str, ...] = (),
        schema_hints: tuple[str, ...] = (),
        allowed_routes: tuple[tuple[str, str], ...] = (),
        configuration_failure: bool = False,
    ) -> None:
        self.reason = reason
        self.response_snapshot = response_snapshot
        self.tool_name = tool_name
        self.missing_fields = missing_fields
        self.schema_hints = schema_hints
        self.allowed_routes = allowed_routes
        self.configuration_failure = configuration_failure
        super().__init__(f"structured tool call protocol error: {reason}")

    def trace_record(self) -> dict[str, Any]:
        """Return machine-readable diagnostics for the internal LLM trace."""
        record: dict[str, Any] = {
            "reason": self.reason,
            "tool_name": self.tool_name,
            "missing_fields": list(self.missing_fields),
            "schema_hints": list(self.schema_hints),
            "allowed_routes": [
                {"adapter": adapter, "action": action}
                for adapter, action in self.allowed_routes
            ],
            "configuration_failure": self.configuration_failure,
            "response": self.response_snapshot,
        }
        return record


class StructuredToolModelClient:
    """OpenAI-compatible transport for one structured tool call per turn."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        request_timeout_seconds: float,
        client: Any | None = None,
        request_observer: Callable[[dict[str, Any]], None] | None = None,
        transport_trace_dir: str | None = None,
    ):
        self.request_timeout_seconds = request_timeout_seconds
        hooks = {}
        if transport_trace_dir is not None and client is None:
            from .model_transport_trace import ModelTransportTrace

            hooks = ModelTransportTrace(transport_trace_dir).hooks
        self.client = (
            client
            if client is not None
            else OpenAI(
                base_url=base_url,
                api_key=api_key,
                max_retries=MODEL_SDK_MAX_RETRIES,
                http_client=httpx.Client(
                    timeout=request_timeout_seconds,
                    trust_env=False,
                    event_hooks=hooks,
                ),
            )
        )
        self.request_observer = request_observer

    def propose(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float,
        output_token_budget: int,
        enable_thinking: bool,
        reasoning_effort: str | None = None,
        reasoning_mode: str | None = None,
        expected_model: str | None = None,
        request_timeout_seconds: float | None = None,
        presence_penalty: float | None = None,
        thinking_token_budget: int | None = None,
        tool_call_stop_sequence: str | None = None,
        deadline_monotonic: float | None = None,
    ) -> dict[str, Any]:
        if (
            reasoning_effort is not None
            and reasoning_effort not in SUPPORTED_REASONING_EFFORTS
        ):
            raise ValueError(f"unsupported reasoning effort: {reasoning_effort!r}")
        if (
            reasoning_mode is not None
            and reasoning_mode not in SUPPORTED_REASONING_MODES
        ):
            raise ValueError(f"unsupported reasoning mode: {reasoning_mode!r}")
        if reasoning_effort is not None and reasoning_mode is not None:
            raise ValueError(
                "reasoning_effort and reasoning_mode are mutually exclusive"
            )
        if reasoning_mode is not None:
            expected_thinking = reasoning_mode == "thinking"
            if enable_thinking is not expected_thinking:
                raise ValueError(
                    "enable_thinking does not match the requested reasoning mode"
                )
        provider_surface, atomic_bindings = atomic_provider_surface(tools)
        request_messages = deepcopy(messages)
        if atomic_bindings:
            guidance = (
                "Discovered atomic__ tools accept action arguments directly at the top level. "
                "Do not supply adapter/action/payload/params wrappers. Put optional request "
                "metadata in request_options. Each call executes one discovered operation."
            )
            first_system = next((m for m in request_messages if m.get("role") == "system"), None)
            if first_system is None:
                request_messages.insert(0, {"role": "system", "content": guidance})
            elif isinstance(first_system.get("content"), list):
                first_system["content"].append({"type": "text", "text": guidance})
            else:
                first_system["content"] = str(first_system.get("content") or "") + "\n" + guidance
        request_tools = _qwen_schema_compatible_tools(model, provider_surface)
        request = {
            "model": model,
            "messages": request_messages,
            "tools": request_tools,
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "stream": True,
            "temperature": temperature,
            "max_tokens": output_token_budget,
            "extra_body": {
                "chat_template_kwargs": {"enable_thinking": enable_thinking}
            },
        }
        if reasoning_effort is not None:
            request["reasoning_effort"] = reasoning_effort
        if presence_penalty is not None:
            request["presence_penalty"] = presence_penalty
        if thinking_token_budget is not None:
            request["extra_body"]["thinking_token_budget"] = thinking_token_budget
        if tool_call_stop_sequence is not None:
            # Retain the complete native delimiter for the provider's tool parser.
            request["stop"] = [tool_call_stop_sequence]
            request["extra_body"]["include_stop_str_in_output"] = True
        constraint = _bounded_qwen_empty_tool_constraint(
            model, request_tools, tool_call_stop_sequence
        )
        if constraint is not None:
            # required/named choices cause vLLM to replace explicit constraints.
            # The explicit grammar enforces the same requirement (at_least_one)
            # and a single call (stop_after_first), with bounded empty bodies.
            request["tool_choice"] = "auto"
            request["extra_body"]["structured_outputs"] = {
                "structural_tag": json.dumps(constraint)
            }
        if self.request_observer is not None:
            self.request_observer(request)
        request_client = self.client
        if request_timeout_seconds is not None:
            timeout = max(float(request_timeout_seconds), 0.1)
            with_options = getattr(self.client, "with_options", None)
            if callable(with_options):
                request_client = with_options(timeout=timeout)
        def aggregate(stream):
            return _aggregate_stream_response(
                stream, progress_timeout_seconds=max(float(
                    request_timeout_seconds if request_timeout_seconds is not None
                    else self.request_timeout_seconds), 0.1),
            )

        if deadline_monotonic is None:
            response = aggregate(
                request_client.chat.completions.create(**request)
            )
        else:
            from .model_deadline import run_before_deadline

            response = run_before_deadline(
                lambda: request_client.chat.completions.create(**request),
                aggregate, deadline_monotonic,
            )
        if (
            expected_model is not None
            and not _same_served_model(expected_model, getattr(response, "model", None))
        ):
            raise StructuredToolProtocolError(
                "response model identity does not match the requested model",
                response_snapshot=self._response_snapshot(response, None, None),
                configuration_failure=True,
            )
        effective_reasoning_mode = self._effective_reasoning_mode(response)
        if reasoning_effort is not None:
            if effective_reasoning_mode is None:
                raise StructuredToolProtocolError(
                    "provider did not attest the effective reasoning effort",
                    response_snapshot=self._response_snapshot(response, None, None),
                    configuration_failure=True,
                )
            if effective_reasoning_mode != reasoning_effort:
                raise StructuredToolProtocolError(
                    "effective reasoning effort does not match the requested effort",
                    response_snapshot=self._response_snapshot(response, None, None),
                    configuration_failure=True,
                )
        if not response.choices:
            raise StructuredToolProtocolError(
                "response contained no choices",
                response_snapshot=self._response_snapshot(response, None, None),
            )
        choice = response.choices[0]
        message = choice.message
        observed_mode = observed_reasoning_mode(response, message)
        if reasoning_mode is not None:
            if observed_mode is None:
                raise StructuredToolProtocolError(
                    "provider did not attest the effective thinking mode",
                    response_snapshot=self._response_snapshot(
                        response, choice, message
                    ),
                    configuration_failure=True,
                )
            if observed_mode != reasoning_mode:
                raise StructuredToolProtocolError(
                    "effective thinking mode does not match the requested mode",
                    response_snapshot=self._response_snapshot(
                        response, choice, message
                    ),
                    configuration_failure=True,
                )
        calls = message.tool_calls or []
        if len(calls) != 1:
            raise StructuredToolProtocolError(
                f"expected exactly one structured tool call, got {len(calls)}",
                response_snapshot=self._response_snapshot(response, choice, message),
            )
        call = calls[0]
        tool = str(call.function.name or "")
        arguments_raw = call.function.arguments
        try:
            arguments = json.loads(arguments_raw or "")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StructuredToolProtocolError(
                "tool arguments are not complete JSON",
                response_snapshot=self._response_snapshot(response, choice, message),
                tool_name=tool,
            ) from exc
        if not isinstance(arguments, dict):
            raise StructuredToolProtocolError(
                "tool arguments must be a JSON object",
                response_snapshot=self._response_snapshot(response, choice, message),
                tool_name=tool,
            )
        provider_tool = tool
        provider_arguments_raw = arguments_raw
        binding = atomic_bindings.get(tool)
        if binding is not None:
            atomic_errors = sorted(
                Draft202012Validator(binding["schema"]).iter_errors(arguments),
                key=lambda error: error.message,
            )
            if atomic_errors:
                actionable = _actionable_validation_errors(atomic_errors)
                raise StructuredToolProtocolError(
                    "tool arguments do not satisfy the exposed atomic schema",
                    response_snapshot=self._response_snapshot(response, choice, message),
                    tool_name=tool,
                    missing_fields=_safe_missing_fields(actionable),
                    schema_hints=_schema_validation_hints(actionable, instance=arguments),
                )
            arguments = restore_adapter_arguments(arguments, binding)
            arguments_raw = json.dumps(arguments, ensure_ascii=False)
            tool = "adapter__adapter_call"
        schema = self._tool_schema(tools, tool)
        if schema is None:
            raise StructuredToolProtocolError(
                "the returned tool is not present in the exposed tool surface",
                response_snapshot=self._response_snapshot(response, choice, message),
                tool_name=tool,
            )
        validator = Draft202012Validator(schema)
        validation_errors = sorted(
            validator.iter_errors(arguments),
            key=lambda error: (
                tuple(str(item) for item in error.absolute_path),
                error.message,
            ),
        )
        allowed_routes: tuple[tuple[str, str], ...] = ()
        route_repaired_from: tuple[str, str] | None = None
        if isinstance(schema, dict):
            properties = schema.get("properties") if isinstance(schema, dict) else None
            action_schema = properties.get("action") if isinstance(properties, dict) else None
            adapter_schema = properties.get("adapter") if isinstance(properties, dict) else None
            action_enum = action_schema.get("enum") if isinstance(action_schema, dict) else None
            adapter_enum = adapter_schema.get("enum") if isinstance(adapter_schema, dict) else None
            raw_routes = schema.get("x-allowed-routes")
            if isinstance(raw_routes, list):
                parsed_routes: list[tuple[str, str]] = []
                for route in raw_routes:
                    if not isinstance(route, dict):
                        continue
                    adapter = route.get("adapter")
                    action = route.get("action")
                    if not isinstance(adapter, str) or not isinstance(action, str):
                        continue
                    pair = (adapter, action)
                    if pair not in parsed_routes:
                        parsed_routes.append(pair)
                allowed_routes = tuple(parsed_routes)
            elif (
                isinstance(action_enum, list)
                and isinstance(adapter_enum, list)
                and action_enum
                and adapter_enum
            ):
                allowed_routes = tuple(
                    (str(adapter), str(action))
                    for adapter in adapter_enum
                    for action in action_enum
                )
        # The provider may ignore JSON-schema enums and replay a stale route
        # from an earlier turn.  An allowlist is a protocol boundary, not a
        # hint: never infer or rewrite the requested route from the payload
        # shape. The caller must re-plan or search for the requested action.
        if tool == "adapter__adapter_call" and allowed_routes:
            requested_adapter = arguments.get("adapter")
            requested_action = arguments.get("action")
            requested_route = (
                requested_adapter,
                requested_action,
            )
            if (
                isinstance(requested_adapter, str)
                and isinstance(requested_action, str)
                and requested_route not in allowed_routes
            ):
                raise StructuredToolProtocolError(
                    "tool route is not in the exposed allowlist",
                    response_snapshot=self._response_snapshot(response, choice, message),
                    tool_name=tool,
                    schema_hints=(
                        "adapter/action must match one of the currently exposed routes; "
                        "call tools_search for the exact required public route",
                    ),
                    allowed_routes=allowed_routes,
                )
        if validation_errors:
            actionable_errors = _actionable_validation_errors(validation_errors)
            raise StructuredToolProtocolError(
                "tool arguments do not satisfy the exposed schema",
                response_snapshot=self._response_snapshot(response, choice, message),
                tool_name=tool,
                missing_fields=_safe_missing_fields(actionable_errors),
                schema_hints=_schema_validation_hints(
                    actionable_errors,
                    instance=arguments,
                ),
                allowed_routes=allowed_routes,
            )
        return {
            "id": call.id,
            "tool": tool,
            "arguments_raw": arguments_raw,
            "provider_tool": provider_tool,
            "provider_arguments_raw": provider_arguments_raw,
            "model_actual": response.model,
            "usage": _jsonable(response.usage),
            "finish_reason": choice.finish_reason,
            "max_output_tokens_requested": output_token_budget,
            "request_timeout_seconds": request_timeout_seconds,
            "response_message": _jsonable(message, exclude_none=True),
            "route_repaired_from": (
                {"adapter": route_repaired_from[0], "action": route_repaired_from[1]}
                if route_repaired_from is not None
                else None
            ),
            # ``length`` can still be valid when only the reasoning suffix was
            # truncated; completeness is established by JSON/schema validation.
            "structured_call_validated": True,
            "reasoning_effort_requested": reasoning_effort,
            "reasoning_effort_effective": self._response_snapshot(
                response, choice, message
            ).get("effective_reasoning_mode"),
            "reasoning_mode_requested": reasoning_mode,
            "reasoning_mode_effective": observed_mode,
            "reasoning_observed": self._reasoning_observed(message),
        }

    @staticmethod
    def _tool_schema(
        tools: list[dict[str, Any]], tool_name: str
    ) -> dict[str, Any] | None:
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function")
            if not isinstance(function, dict) or function.get("name") != tool_name:
                continue
            schema = function.get("parameters")
            return schema if isinstance(schema, dict) else None
        return None

    @staticmethod
    def _response_snapshot(
        response: Any, choice: Any | None, message: Any | None
    ) -> dict[str, Any]:
        usage = getattr(response, "usage", None)
        usage = _jsonable(usage)
        message_dump = _jsonable(message, exclude_none=True)
        snapshot = {
            "model": getattr(response, "model", None),
            "finish_reason": getattr(choice, "finish_reason", None),
            "usage": usage,
            "message": message_dump,
        }
        effective = StructuredToolModelClient._effective_reasoning_mode(response)
        if effective is not None:
            snapshot["effective_reasoning_mode"] = effective
        observed = observed_reasoning_mode(response, message)
        if observed is not None:
            snapshot["observed_reasoning_mode"] = observed
        return snapshot

    @staticmethod
    def _effective_reasoning_mode(response: Any) -> str | None:
        """Read an explicit provider attestation without inferring from text.

        OpenAI-compatible clients expose response extensions in a few shapes:
        as top-level fields, ``model_extra``/metadata dictionaries, or the
        serialized response object.  We inspect only those structured fields;
        a non-empty ``reasoning`` message is deliberately not evidence of the
        selected provider mode.
        """
        candidates: list[object] = []
        if isinstance(response, dict):
            candidates.append(response)
        else:
            candidates.append(
                {
                    key: getattr(response, key, None)
                    for key in (
                        "effective_reasoning_effort",
                        "effective_reasoning_mode",
                        "reasoning_effort",
                        "reasoning_mode",
                    )
                }
            )
            for key in ("model_extra", "response_metadata", "metadata"):
                value = getattr(response, key, None)
                if isinstance(value, dict):
                    candidates.append(value)
            model_dump = getattr(response, "model_dump", None)
            if callable(model_dump):
                try:
                    dumped = model_dump(mode="json", exclude_none=True)
                except (AttributeError, TypeError, ValueError):
                    dumped = None
                if isinstance(dumped, dict):
                    candidates.append(dumped)
        for candidate in candidates:
            effective = explicit_effective_reasoning_mode(candidate)
            if effective is not None:
                return effective
        return None

    @staticmethod
    def _reasoning_observed(message: Any) -> bool:
        """Record only whether the provider returned a non-empty reasoning field."""
        reasoning = getattr(message, "reasoning", None)
        if reasoning is None:
            reasoning = getattr(message, "reasoning_content", None)
        if reasoning is None and hasattr(message, "model_dump"):
            try:
                dumped = message.model_dump(mode="json")
                reasoning = dumped.get("reasoning")
                if reasoning is None:
                    reasoning = dumped.get("reasoning_content")
            except (AttributeError, TypeError, ValueError):
                reasoning = None
        return isinstance(reasoning, str) and bool(reasoning.strip())
