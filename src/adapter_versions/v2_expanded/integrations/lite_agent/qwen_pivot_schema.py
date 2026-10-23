"""Lower pivot intersections to complete, disjoint Qwen XML alternatives.

XGrammar 0.2.8 does not intersect object siblings with oneOf/allOf. Keep the
public schema for validation, but distribute its constraints into complete
objects before using it for constrained generation. Unknown contract shapes
fail closed rather than being silently discarded.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re

from jsonschema import Draft202012Validator

from calc_adapter.schema import A1_RANGE_PATTERN


class UnsupportedPivotSchema(ValueError):
    pass


def _intersect(left: dict, right: dict) -> dict:
    result = deepcopy(left)
    for key, value in right.items():
        if key not in result:
            result[key] = deepcopy(value)
        elif key == "properties":
            for name, schema in value.items():
                result[key][name] = _intersect(result[key].get(name, {}), schema)
        elif key == "required":
            result[key] = list(dict.fromkeys(result[key] + value))
        elif key == "items":
            result[key] = _intersect(result[key], value)
        elif key in {"minimum", "minItems", "minLength", "minProperties"}:
            result[key] = max(result[key], value)
        elif key in {"maximum", "maxItems", "maxLength", "maxProperties"}:
            result[key] = min(result[key], value)
        elif key == "additionalProperties" and value is False:
            result[key] = False
        elif key == "enum":
            result[key] = [v for v in result[key] if v in value]
        elif key in {"description", "title", "$comment"}:
            continue
        elif result[key] != value:
            raise UnsupportedPivotSchema(f"cannot intersect pivot keyword {key}")
    if "const" in result:
        if not Draft202012Validator(left).is_valid(result["const"]) or not Draft202012Validator(right).is_valid(result["const"]):
            raise UnsupportedPivotSchema("inconsistent pivot constant")
    if result.get("enum") == []:
        raise UnsupportedPivotSchema("empty pivot enumeration")
    return result


_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_ALPHABET = "$:" + "0123456789" + _LETTERS


def _next(state: tuple[int, int, bool], char: str) -> tuple[int, int, bool] | None:
    phase, letters, second = state
    if phase == 0 and char == "$":
        return 1, 0, second
    if phase in {0, 1, 2} and char in _LETTERS and letters < 4:
        return 2, letters + 1, second
    if phase == 2 and char == "$":
        return 3, letters, second
    if phase in {2, 3} and char in "123456789":
        return 4, letters, second
    if phase == 4:
        if char in "0123456789":
            return state
        if char == ":" and not second:
            return 0, 0, True
    return None


def _suffix(state: tuple[int, int, bool]) -> str:
    phase, letters, second = state
    cell = r"\$?[A-Za-z]{1,4}\$?[1-9][0-9]*"
    rest = "" if second else "(?::" + cell + ")?"
    if phase == 0:
        return cell + rest
    if phase == 1:
        return r"[A-Za-z]{1,4}\$?[1-9][0-9]*" + rest
    if phase == 2:
        extra = "[A-Za-z]{0," + str(4 - letters) + "}" if letters < 4 else ""
        return extra + r"\$?[1-9][0-9]*" + rest
    if phase == 3:
        return r"[1-9][0-9]*" + rest
    return "[0-9]*" + rest


def _excluding_ranges(values: list[str]) -> str:
    """Exact regular-language difference: A1 ranges minus finite literals.

    A trie follows excluded prefixes. Once a character differs, the ordinary
    A1 suffix is allowed. This needs neither unsupported negative lookahead nor
    a lossy `not: enum` constraint. Longer/shorter valid references remain legal.
    """
    trie: dict = {}
    for value in values:
        if not isinstance(value, str):
            raise UnsupportedPivotSchema("pivot range enum must contain strings")
        if not A1_RANGE_PATTERN.fullmatch(value):
            continue  # Outside the underlying language already.
        node = trie
        for char in value:
            node = node.setdefault(char, {})
        node[None] = True

    def visit(state: tuple[int, int, bool], node: dict) -> str:
        alternatives = [""] if state[0] == 4 and None not in node else []
        divergent: dict[tuple, list[str]] = {}
        for char in _ALPHABET:
            following = _next(state, char)
            if following is None:
                continue
            if char in node:
                alternatives.append(re.escape(char) + visit(following, node[char]))
            else:
                divergent.setdefault(following, []).append(char)
        for following, chars in divergent.items():
            alternatives.append("[" + re.escape("".join(chars)) + "]" + _suffix(following))
        return "(?:" + "|".join(alternatives) + ")"

    return "^" + visit((0, 0, False), trie) + "$"


_PLACEMENT = {"oneOf": [
    {"required": ["destination"], "not": {"anyOf": [
        {"required": ["below_range"]}, {"required": ["blank_rows"]},
    ]}},
    {"required": ["below_range", "blank_rows"], "not": {"required": ["destination"]}},
]}


def pivot_generation_schema(schema: dict) -> dict:
    """Equivalent complete alternatives, retaining top-level parser type hints."""
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise UnsupportedPivotSchema("pivot must be a closed object")
    if set(schema) - {"type", "properties", "required", "additionalProperties", "oneOf", "allOf", "description"}:
        raise UnsupportedPivotSchema("unknown pivot object constraint")
    conjunctions = schema.get("allOf", [])
    if not conjunctions or conjunctions[0] != _PLACEMENT:
        raise UnsupportedPivotSchema("unknown pivot placement contract")
    conditions: dict[str, dict] = {}
    for clause in conjunctions[1:]:
        try:
            values = clause["if"]["properties"]["below_range"]["enum"]
            gap = clause["then"]["properties"]["blank_rows"]
        except (KeyError, TypeError) as exc:
            raise UnsupportedPivotSchema("unknown pivot conditional") from exc
        expected = {"if": {"properties": {"below_range": {"enum": values}}, "required": ["below_range"]},
                    "then": {"properties": {"blank_rows": gap}, "required": ["blank_rows"]}}
        if clause != expected or set(gap) - {"type", "minimum", "maximum", "const"}:
            raise UnsupportedPivotSchema("unknown pivot gap condition")
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise UnsupportedPivotSchema("pivot range enum must contain strings")
        for value in values:
            conditions[value] = _intersect(conditions.get(value, {}), gap)
    base = {k: deepcopy(v) for k, v in schema.items() if k not in {"oneOf", "allOf"}}
    categories = schema.get("oneOf", [{}])
    if "oneOf" in schema:
        # Distribution preserves oneOf only when the categories are disjoint.
        # The catalog discriminates them by the complete row_fields constant.
        groups = [category.get("properties", {}).get("row_fields", {}).get("const") for category in categories]
        if not groups or any(not isinstance(group, list) or not group for group in groups):
            raise UnsupportedPivotSchema("unknown pivot category discriminator")
        if len({json.dumps(group, sort_keys=True) for group in groups}) != len(groups):
            raise UnsupportedPivotSchema("overlapping pivot categories")
    branches = []
    for category in categories:
        if set(category) - {"properties", "required"}:
            raise UnsupportedPivotSchema("unknown pivot category branch")
        complete = _intersect(base, category)
        for relative in (False, True):
            branch = deepcopy(complete)
            forbidden = {"destination"} if relative else {"below_range", "blank_rows"}
            for key in forbidden:
                branch["properties"].pop(key, None)
            branch["required"] = list(dict.fromkeys(branch.get("required", []) + (
                ["below_range", "blank_rows"] if relative else ["destination"])))
            if forbidden.intersection(branch["required"]):
                raise UnsupportedPivotSchema("conflicting required pivot location")
            if not relative or not conditions:
                branches.append(branch)
                continue
            reference = branch["properties"]["below_range"]
            if {k: v for k, v in reference.items() if k != "description"} != {
                "type": "string", "pattern": A1_RANGE_PATTERN.pattern,
            }:
                raise UnsupportedPivotSchema("unknown relative reference constraints")
            groups: dict[str, list[str]] = {}
            for value, gap in conditions.items():
                if A1_RANGE_PATTERN.fullmatch(value):
                    groups.setdefault(json.dumps(gap, sort_keys=True), []).append(value)
            for gap_json, values in groups.items():
                known = deepcopy(branch)
                known["properties"]["below_range"] = {**reference, "enum": values}
                known["properties"]["blank_rows"] = _intersect(known["properties"]["blank_rows"], json.loads(gap_json))
                branches.append(known)
            branch["properties"]["below_range"]["pattern"] = _excluding_ranges(list(conditions))
            branches.append(branch)
    # Qwen's tool parser still needs root properties for XML -> JSON typing.
    # XGrammar dispatches on oneOf: EVERY branch must therefore stand alone.
    return {**base, "oneOf": branches}


def lower_pivot_schemas(value):
    """Handle direct actions and nested adapter.call payload.params alike."""
    if isinstance(value, list):
        return [lower_pivot_schemas(child) for child in value]
    if not isinstance(value, dict):
        return value
    properties = value.get("properties", {})
    if {"source_sheet", "source_range", "destination_sheet", "name", "data_fields", "below_range", "blank_rows"} <= properties.keys():
        return pivot_generation_schema(value)
    return {key: lower_pivot_schemas(child) for key, child in value.items()}
