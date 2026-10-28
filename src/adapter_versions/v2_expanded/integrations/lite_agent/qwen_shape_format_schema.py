"""Preserve the nonempty Impress formatting contract in Qwen XML generation.

Complete alternatives avoid intersecting required target fields with partial
anyOf branches. Arguments stay flat and are checked against the original schema.
"""
from copy import deepcopy

from impress_adapter.tool_manifest import TEXT_FORMAT_PROPERTIES

from .atomic_tool_surface import OPTIONS_FIELD


FORMAT_FIELDS = (*TEXT_FORMAT_PROPERTIES, "bullet", "level", "left_margin", "first_line_indent")
_SHAPE_FIELDS = {"slide", "selector", "match_text", "lines", *FORMAT_FIELDS}


class UnsupportedShapeFormatSchema(ValueError):
    pass


def _complete_alternatives(schema: dict) -> dict:
    allowed = {"type", "properties", "required", "additionalProperties", "anyOf",
               "description", "title", "$comment"}
    if (set(schema) - allowed
            or schema.get("type") != "object"
            or schema.get("additionalProperties") is not False
            or set(schema.get("properties", {})) - {OPTIONS_FIELD} != _SHAPE_FIELDS
            or schema.get("required") != ["slide", "selector"]
            or schema.get("anyOf") != [{"required": [field]} for field in FORMAT_FIELDS]):
        raise UnsupportedShapeFormatSchema("unknown shape.format_text generation contract")
    base = {key: deepcopy(value) for key, value in schema.items() if key != "anyOf"}
    branches = []
    for index, field in enumerate(FORMAT_FIELDS):
        branch = deepcopy(base)
        # Partition by the first supplied formatting field. Multi-field calls
        # match exactly one branch, with all original value constraints intact.
        for earlier in FORMAT_FIELDS[:index]:
            del branch["properties"][earlier]
        branch["required"].append(field)
        branches.append(branch)
    # Qwen's XML parser still needs root properties for parameter type hints.
    return {**base, "oneOf": branches}


def _lower_schema(schema):
    if not isinstance(schema, dict):
        return deepcopy(schema)
    properties = schema.get("properties", {})
    if isinstance(properties, dict) and _SHAPE_FIELDS <= properties.keys():
        return _complete_alternatives(schema)
    result = deepcopy(schema)
    # Visit schema positions only. Never rewrite JSON literals in enum, const,
    # default, examples, or a property whose name happens to be a schema keyword.
    for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
        if isinstance(result.get(key), dict):
            result[key] = {name: _lower_schema(value) for name, value in result[key].items()}
    for key in ("items", "additionalItems", "additionalProperties", "contains", "propertyNames",
                "not", "if", "then", "else", "unevaluatedItems", "unevaluatedProperties"):
        if isinstance(result.get(key), dict):
            result[key] = _lower_schema(result[key])
        elif key == "items" and isinstance(result.get(key), list):
            result[key] = [_lower_schema(child) for child in result[key]]
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        if isinstance(result.get(key), list):
            result[key] = [_lower_schema(child) for child in result[key]]
    if isinstance(result.get("dependencies"), dict):
        result["dependencies"] = {key: _lower_schema(value) if isinstance(value, dict) else value
                                  for key, value in result["dependencies"].items()}
    return result


def lower_shape_format_schemas(tools: list[dict]) -> list[dict]:
    """Lower direct and nested action schemas without changing tool identities."""
    result = deepcopy(tools)
    for tool in result:
        function = tool.get("function", {})
        if "parameters" in function:
            function["parameters"] = _lower_schema(function["parameters"])
    return result
