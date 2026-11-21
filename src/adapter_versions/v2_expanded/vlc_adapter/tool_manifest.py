from __future__ import annotations

from typing import Any

from .atomic_preferences import ATOMIC_PREFERENCE_SCHEMAS


STRICT_ACTION_PARAM_SCHEMAS: dict[str, dict[str, Any]] = {
    "playback.status": {
        "description": (
            "Read playback state, time, position and the current media source. source is "
            "an absolute local path or a stream URI observed in VLC's playlist; source_uri "
            "retains the original URI. A null source is unknown, with source_error when "
            "lookup failed. metadata.filename and title are display labels, not file paths. "
            "time_seconds is the matching player's fractional playback position from "
            "native position_microseconds; preserve its precision when selecting a media "
            "time. time is only whole seconds. If precise time is unavailable, time_error "
            "explains why; do not treat whole seconds as an exact video frame."
        ),
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    "playback.open": {
        "description": (
            "Open exactly one model-selected local media path or HTTP(S) stream. Use the "
            "generic filesystem.find tool first when a local path is not known; this action "
            "does not search directories or choose among candidate files."
        ),
        "properties": {
            "source": {
                "type": "string",
                "minLength": 1,
                "description": "Exact local media path returned by observation, or an explicit HTTP(S) URL.",
            },
            "loop": {
                "type": "boolean",
                "description": "Whether VLC should loop this media; defaults to false.",
            },
        },
        "required": ["source"],
        "additionalProperties": False,
    },
    "media.flip_video": {
        "description": (
            "Flip one complete local video and save a new MP4. Choose vertical to reverse "
            "top and bottom for an upside-down flipped picture; choose horizontal only "
            "for a left/right mirror image. This does not trim or select a clip."
        ),
        "properties": {
            "input_path": {
                "type": "string", "minLength": 1,
                "description": "Absolute path of the existing source video.",
            },
            "output_path": {
                "type": "string", "minLength": 1, "pattern": r"^/.*\.[mM][pP]4$",
                "description": "Distinct absolute .mp4 output path selected from the request.",
            },
            "axis": {
                "type": "string", "enum": ["vertical", "horizontal"],
                "description": (
                    "vertical reverses top/bottom; horizontal mirrors left/right. "
                    "Select exactly one axis."
                ),
            },
        },
        "required": ["input_path", "output_path", "axis"],
        "additionalProperties": False,
    },
}

STRICT_ACTION_PARAM_SCHEMAS.update(ATOMIC_PREFERENCE_SCHEMAS)
