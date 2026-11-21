from __future__ import annotations


from .atomic_preferences import validate_atomic_params, ATOMIC_PREFERENCES
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .errors import AdapterError


ADAPTER_NAME = "vlc"
MIN_TIMEOUT_MS = 100
MAX_TIMEOUT_MS = 900_000
DEFAULT_TIMEOUT_MS = 60_000

ACTIONS = frozenset(
    {
        *ATOMIC_PREFERENCES,
        "media.flip_video",

        "playback.open",
        "playback.status",
        "window.set_fullscreen",
        "media.extract_audio",
        "media.extract_subtitles",
        "media.transcode_clip",
        "media.extract_frame",
    }
)

VERIFY_TYPES = frozenset(
    {
        "config",
        "status",
        "playback",
        "window_fullscreen",
        "media",
        "subtitle",
        "wallpaper",
    }
)


@dataclass(frozen=True)
class ActionRequest:
    request_id: str
    adapter: str
    action: str
    timeout_ms: int
    params: dict[str, Any]
    verify: list[dict[str, Any]]

    def to_worker_payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action": self.action,
            "timeout_ms": self.timeout_ms,
            "params": self.params,
            "verify": self.verify,
        }


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AdapterError("INVALID_REQUEST", f"{field} must be an object")
    return dict(value)


def _string(data: Mapping[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(
            "INVALID_REQUEST", f"params.{field} must be a non-empty string"
        )
    return value


def _boolean(data: Mapping[str, Any], field: str) -> None:
    if not isinstance(data.get(field), bool):
        raise AdapterError("INVALID_REQUEST", f"params.{field} must be a boolean")


def _integer(data: Mapping[str, Any], field: str, minimum: int, maximum: int) -> int:
    value = data.get(field)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise AdapterError(
            "INVALID_REQUEST",
            f"params.{field} must be an integer from {minimum} to {maximum}",
        )
    return value


def _number(
    data: Mapping[str, Any],
    field: str,
    minimum: float,
    maximum: float,
    *,
    exclusive_minimum: bool = False,
) -> float:
    value = data.get(field)
    valid_type = isinstance(value, (int, float)) and not isinstance(value, bool)
    numeric = float(value) if valid_type else None
    valid_minimum = bool(
        numeric is not None
        and (numeric > minimum if exclusive_minimum else numeric >= minimum)
    )
    if numeric is None or not valid_minimum or numeric > maximum:
        comparison = "greater than" if exclusive_minimum else "at least"
        raise AdapterError(
            "INVALID_REQUEST",
            f"params.{field} must be a number {comparison} {minimum} and at most {maximum}",
        )
    return numeric


def _verification(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AdapterError("INVALID_REQUEST", "verify must be an array")
    checks = []
    for index, raw in enumerate(value):
        check = _mapping(raw, f"verify[{index}]")
        if check.get("type") not in VERIFY_TYPES:
            raise AdapterError(
                "INVALID_REQUEST",
                f"verify[{index}].type is unsupported",
                {"type": check.get("type")},
            )
        checks.append(check)
    return checks


RETIRED_ACTION_REPLACEMENTS = {
    'preferences.configure': [name for name in ACTIONS if name.startswith('preferences.set_')],
    'config.update': [name for name in ACTIONS if name.startswith('preferences.set_')],
}


def _reject_retired_action(action: str) -> None:
    replacements = RETIRED_ACTION_REPLACEMENTS.get(action)
    if replacements is not None:
        raise AdapterError('UNSUPPORTED_ACTION', f"{action} has been retired; call one registered single-operation replacement at a time: {', '.join(replacements)}",
            {"conflicting_action": action, "replacement_actions": replacements,
             "correct_usage": "Use tools_search to obtain the replacement schema, then provide only its documented fields in a separate call."})


def validate_action_params(action: str, params: Mapping[str, Any]) -> None:
    _reject_retired_action(action)
    if action not in ACTIONS:
        raise AdapterError("UNSUPPORTED_ACTION", "action is not supported", {"action": action}, 404)
    if action in ATOMIC_PREFERENCES:
        validate_atomic_params(action, params)
        return
    if action == "media.flip_video":
        allowed = {"input_path", "output_path", "axis"}
        unknown = sorted(set(params) - allowed)
        if unknown:
            raise AdapterError(
                "INVALID_REQUEST",
                "media.flip_video accepts one axis and one input/output video pair",
                {"conflicting_fields": unknown, "allowed": sorted(allowed)},
            )
        _string(params, "input_path")
        _string(params, "output_path")
        if params.get("axis") not in {"vertical", "horizontal"}:
            raise AdapterError(
                "INVALID_REQUEST",
                "params.axis must be vertical (top/bottom) or horizontal (left/right)",
                {"axis": params.get("axis")},
            )
        if Path(params["input_path"]).expanduser().resolve() == Path(
            params["output_path"]
        ).expanduser().resolve():
            raise AdapterError(
                "INVALID_REQUEST",
                "media.flip_video requires a separate output_path; keep input_path unchanged",
            )
    elif action == "playback.open":
        allowed = {"source", "loop"}
        unknown = sorted(set(params) - allowed)
        if unknown:
            raise AdapterError(
                "INVALID_REQUEST",
                "playback.open contains unsupported fields",
                {"unsupported_fields": unknown, "allowed": sorted(allowed)},
            )
        _string(params, "source")
        if "loop" in params and not isinstance(params["loop"], bool):
            raise AdapterError("INVALID_REQUEST", "params.loop must be a boolean")
    elif action == "playback.status":
        if params:
            raise AdapterError("INVALID_REQUEST", "playback.status takes no parameters")
    elif action == "window.set_fullscreen":
        _boolean(params, "enabled")
    elif action == "media.extract_audio":
        _string(params, "input_path")
        _string(params, "output_path")
        unknown = sorted(set(params) - {"input_path", "output_path"})
        if unknown:
            raise AdapterError(
                "INVALID_REQUEST",
                f"{action} contains unsupported fields",
                {"unsupported_fields": unknown},
            )
    elif action == "media.extract_subtitles":
        _string(params, "input_path")
        _string(params, "output_path")
        if "subtitle_stream_index" in params:
            _integer(params, "subtitle_stream_index", 0, 1024)
    elif action == "media.transcode_clip":
        _string(params, "input_path")
        _string(params, "output_path")
        _number(params, "start_time_seconds", 0, 86_400)
        _number(
            params,
            "duration_seconds",
            0,
            86_400,
            exclusive_minimum=True,
        )
        if "frame_rate" in params:
            _number(params, "frame_rate", 1, 60)
    elif action == "media.extract_frame":
        allowed = {"input_path", "output_path", "frame_index", "time_seconds"}
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            raise AdapterError(
                "INVALID_REQUEST",
                "media.extract_frame received unsupported parameters",
                {"unexpected": unexpected, "allowed": sorted(allowed)},
            )
        _string(params, "input_path")
        _string(params, "output_path")
        has_frame_index = "frame_index" in params
        has_time_seconds = "time_seconds" in params
        if has_frame_index == has_time_seconds:
            raise AdapterError(
                "INVALID_REQUEST",
                "params requires exactly one of frame_index or time_seconds",
            )
        if has_frame_index:
            _integer(params, "frame_index", 0, 10_000_000)
        else:
            _number(params, "time_seconds", 0, 86_400)


def parse_action_request(raw: Any) -> ActionRequest:
    data = _mapping(raw, "request")
    action = data.get("action")
    _reject_retired_action(action)
    if action not in ACTIONS:
        raise AdapterError(
            "UNSUPPORTED_ACTION", "unsupported VLC action", {"action": action}
        )
    adapter = data.get("adapter", ADAPTER_NAME)
    if adapter != ADAPTER_NAME:
        raise AdapterError("INVALID_REQUEST", f"adapter must be {ADAPTER_NAME}")
    request_id = data.get("request_id") or str(uuid4())
    if not isinstance(request_id, str) or not request_id.strip():
        raise AdapterError("INVALID_REQUEST", "request_id must be a non-empty string")
    timeout_ms = data.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    if (
        isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, int)
        or not MIN_TIMEOUT_MS <= timeout_ms <= MAX_TIMEOUT_MS
    ):
        raise AdapterError(
            "INVALID_REQUEST",
            f"timeout_ms must be from {MIN_TIMEOUT_MS} to {MAX_TIMEOUT_MS}",
        )
    params = _mapping(data.get("params"), "params")
    validate_action_params(action, params)
    return ActionRequest(
        request_id=request_id,
        adapter=adapter,
        action=action,
        timeout_ms=timeout_ms,
        params=params,
        verify=_verification(data.get("verify")),
    )
