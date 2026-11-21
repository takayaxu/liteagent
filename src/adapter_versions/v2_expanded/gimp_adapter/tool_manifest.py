from __future__ import annotations

from typing import Any
from .edit_session import SCHEMAS as SESSION_SCHEMAS


STRICT_ACTION_PARAM_SCHEMAS: dict[str, dict[str, Any]] = {
    "image.inspect": {
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Exact local path or file URL of the image to inspect. Use "
                    "filesystem.find first when only a basename or unknown location is given."
                ),
            }
        },
        "required": ["path"],
    },

    "image.crop": {
        "properties": {
            "input_path": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Exact local path or file URL of the source raster image. Use "
                    "filesystem.find first when only a basename or unknown location is given."
                ),
            },
            "output_path": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Destination raster path. A basename with no directory is saved beside "
                    "input_path; it is not saved in the process home or working directory."
                ),
            },
            "unit": {
                "type": "string",
                "enum": ["percent", "pixels"],
                "description": (
                    "How all four edge amounts are interpreted. In percent mode, 20 means "
                    "twenty percent of that edge's image dimension, not 0.20."
                ),
            },
            "top": {
                "type": "number",
                "minimum": 0,
                "description": "Amount removed from the top edge; defaults to 0.",
            },
            "right": {
                "type": "number",
                "minimum": 0,
                "description": "Amount removed from the right edge; defaults to 0.",
            },
            "bottom": {
                "type": "number",
                "minimum": 0,
                "description": "Amount removed from the bottom edge; defaults to 0.",
            },
            "left": {
                "type": "number",
                "minimum": 0,
                "description": "Amount removed from the left edge; defaults to 0.",
            },
            "overwrite": {
                "type": "boolean",
                "default": False,
                "description": "Replace an existing destination only when true.",
            },
        },
        "required": ["input_path", "output_path", "unit"],
        "anyOf": [
            {"required": ["top"]},
            {"required": ["right"]},
            {"required": ["bottom"]},
            {"required": ["left"]},
        ],
    },
    "image.export": {
        "description": (
            "Export a saved source image or XCF project to a separate image file. "
            "Supply both input_path and output_path inside params; target.path does "
            "not select the source. The output suffix chooses PNG, JPEG or XCF; "
            "there is no file_type field. Use exact filesystem paths, not ~/ or file URLs. "
            "This reads the saved input and does not export an unsaved GUI buffer. "
            "Existing output artifacts are replaced; the input must be different."
        ),
        "properties": {
            "input_path": {"type": "string", "minLength": 1, "pattern": r"^[\s\S]*\S[\s\S]*$"},
            "output_path": {"type": "string", "minLength": 1, "pattern": r"^[\s\S]*\S[\s\S]*$"},
            "loader": {"type": "string", "enum": ["auto", "jpeg"],
                       "description": "Defaults to auto; jpeg explicitly forces the JPEG loader."},
            "quality": {"type": "number", "minimum": 0, "maximum": 1,
                        "description": "JPEG quality from 0 to 1, default 0.98; not a percentage."},
        },
        "required": ["input_path", "output_path"],
    },
}

STRICT_ACTION_PARAM_SCHEMAS.update(SESSION_SCHEMAS)
