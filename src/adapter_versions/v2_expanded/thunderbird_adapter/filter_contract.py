from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from .errors import AdapterError


FILTER_FIELDS = {
    "subject": "subject",
    "sender": "from",
    "recipient": "to",
    "cc": "cc",
    "body": "body",
}
FILTER_OPERATORS = {
    "contains": "contains",
    "does_not_contain": "doesn't contain",
    "is": "is",
    "is_not": "isn't",
    "begins_with": "begins with",
    "ends_with": "ends with",
}
FILTER_ACTIONS = {
    "move_to_local_folder": "Move to folder",
    "forward": "Forward",
}


def _plain_string(value: Any, field: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError("INVALID_REQUEST", f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_length or any(char in normalized for char in "\r\n\x00"):
        raise AdapterError(
            "INVALID_REQUEST",
            f"{field} must be at most {max_length} characters without line breaks",
        )
    return normalized


def validate_local_folder_name(value: Any, field: str = "folder name") -> str:
    name = _plain_string(value, field, max_length=255)
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise AdapterError(
            "INVALID_REQUEST",
            f"{field} must be one Thunderbird local-folder name, not a path",
        )
    return name


def validate_filter_configuration(params: Mapping[str, Any]) -> None:
    if "filters" in params:
        raise AdapterError(
            "INVALID_REQUEST",
            "params.filters is no longer supported; call filters.configure once per rule with params.filter, and call folders.ensure_local first for move_to_local_folder",
        )
    unexpected = sorted(set(params).difference({"filter"}))
    if unexpected:
        raise AdapterError(
            "INVALID_REQUEST",
            f"filters.configure received unsupported parameters: {unexpected}",
        )
    rule = params.get("filter")
    if not isinstance(rule, Mapping):
        raise AdapterError("INVALID_REQUEST", "params.filter must be one rule object")
    allowed_rule_fields = {
        "name",
        "enabled",
        "match",
        "condition_mode",
        "conditions",
        "action",
        "destination",
    }
    allowed_condition_fields = {"field", "operator", "value"}
    field = "params.filter"
    unexpected_rule_fields = sorted(set(rule).difference(allowed_rule_fields))
    if unexpected_rule_fields:
        raise AdapterError(
            "INVALID_REQUEST",
            f"{field} contains unsupported fields: {unexpected_rule_fields}",
        )
    if "name" in rule:
        _plain_string(rule["name"], f"{field}.name", max_length=255)
    if "enabled" in rule and not isinstance(rule["enabled"], bool):
        raise AdapterError("INVALID_REQUEST", f"{field}.enabled must be a boolean")
    if rule.get("match", "all") not in {"all", "any"}:
        raise AdapterError("INVALID_REQUEST", f"{field}.match must be all or any")
    condition_mode = rule.get("condition_mode")
    if condition_mode not in {"criteria", "all_messages"}:
        raise AdapterError(
            "INVALID_REQUEST",
            f"{field}.condition_mode must be criteria or all_messages",
        )
    action = rule.get("action")
    if action not in FILTER_ACTIONS:
        raise AdapterError(
            "INVALID_REQUEST", f"{field}.action must be move_to_local_folder or forward"
        )
    destination = _plain_string(
        rule.get("destination"), f"{field}.destination", max_length=512
    )
    if action == "move_to_local_folder":
        validate_local_folder_name(destination, f"{field}.destination")
    conditions = rule.get("conditions")
    if not isinstance(conditions, list) or len(conditions) > 10:
        raise AdapterError(
            "INVALID_REQUEST",
            f"{field}.conditions must be an explicit array with at most 10 items",
        )
    if condition_mode == "criteria" and not conditions:
        raise AdapterError(
            "INVALID_REQUEST",
            f"{field}.conditions must contain at least one item for condition_mode=criteria",
        )
    if condition_mode == "all_messages" and conditions:
        raise AdapterError(
            "INVALID_REQUEST",
            f"{field}.conditions must be empty for condition_mode=all_messages",
        )
    for condition_index, condition in enumerate(conditions):
        condition_field = f"{field}.conditions[{condition_index}]"
        if not isinstance(condition, Mapping):
            raise AdapterError(
                "INVALID_REQUEST", f"{condition_field} must be an object"
            )
        unexpected_condition_fields = sorted(
            set(condition).difference(allowed_condition_fields)
        )
        if unexpected_condition_fields:
            raise AdapterError(
                "INVALID_REQUEST",
                f"{condition_field} contains unsupported fields: "
                f"{unexpected_condition_fields}",
            )
        if condition.get("field") not in FILTER_FIELDS:
            raise AdapterError(
                "INVALID_REQUEST", f"{condition_field}.field is unsupported"
            )
        if condition.get("operator") not in FILTER_OPERATORS:
            raise AdapterError(
                "INVALID_REQUEST", f"{condition_field}.operator is unsupported"
            )
        _plain_string(
            condition.get("value"), f"{condition_field}.value", max_length=1024
        )


def _condition_value(value: str) -> str:
    if not any(char in value for char in ',()"'):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def compile_filter_configuration(params: Mapping[str, Any]) -> dict[str, Any]:
    validate_filter_configuration(params)
    rule = params["filter"]
    action = rule["action"]
    destination = rule["destination"].strip()
    if rule["condition_mode"] == "criteria":
        connective = "AND" if rule.get("match", "all") == "all" else "OR"
        condition = " ".join(
            f"{connective} ({FILTER_FIELDS[item['field']]},"
            f"{FILTER_OPERATORS[item['operator']]},"
            f"{_condition_value(item['value'].strip())})"
            for item in rule["conditions"]
        )
    else:
        condition = "ALL"
    local_folder = destination if action == "move_to_local_folder" else None
    action_value = (
        "mailbox://nobody@Local%20Folders/" + quote(destination, safe="")
        if local_folder
        else destination
    )
    default_name = (
        f"Move matching messages to {destination}"
        if local_folder
        else f"Forward matching messages to {destination}"
    )
    return {
        "filter": {
            "name": rule.get("name", default_name).strip(),
            "enabled": "yes" if rule.get("enabled", True) else "no",
            "type": "17",
            "action": FILTER_ACTIONS[action],
            "actionValue": action_value,
            "condition": condition,
        },
        "local_folder": local_folder,
    }
