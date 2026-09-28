from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from .errors import AdapterError
from .filter_contract import validate_filter_configuration


ADAPTER_NAME = "thunderbird"
MIN_TIMEOUT_MS = 100
MAX_TIMEOUT_MS = 900_000
DEFAULT_TIMEOUT_MS = 60_000
ACTIONS = frozenset(
    {
        "identity.set_plain_text_signature",
        "identity.set_reply_quoting",
        "filters.set_subfolder_application",
        "inbox.set_unified",
        "theme.set_dark_mode",
        "xulstore.update",
        "folders.ensure_local",
        "filters.configure",
        "messages.export_eml",
        "contacts.export_csv",
        "messages.query",
        "identities.query",
        "attachments.save",
        "accounts.remove",
        "compose.attach",
        "compose.set_recipients",
        "ui.prefill_account_setup",
    }
)
VERIFY_TYPES = frozenset(
    {
        "preferences",
        "json_path",
        "folders",
        "filters",
        "exported_eml",
        "exported_contacts",
        "attachment_file",
        "account_removed",
        "accessibility",
    }
)

RETIRED_ACTION_REPLACEMENTS = {
    "mail.configure": [
        "identity.set_plain_text_signature",
        "identity.set_reply_quoting",
        "filters.set_subfolder_application",
        "inbox.set_unified",
        "theme.set_dark_mode",
    ]
}


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


def _string_list(
    data: Mapping[str, Any], field: str, *, required: bool = True
) -> list[str]:
    value = data.get(field)
    if value is None and not required:
        return []
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise AdapterError(
            "INVALID_REQUEST", f"params.{field} must be a non-empty string array"
        )
    return value


def _reject_unexpected_fields(
    action: str, params: Mapping[str, Any], allowed: set[str]
) -> None:
    unexpected = sorted(set(params).difference(allowed))
    if unexpected:
        raise AdapterError(
            "INVALID_REQUEST",
            f"{action} received unsupported parameters: {unexpected}",
            {"unsupported_fields": unexpected, "allowed_fields": sorted(allowed)},
        )


def _validate_identity(params: Mapping[str, Any]) -> None:
    identity = _string(params, "identity")
    if not identity.replace("_", "").replace("-", "").isalnum():
        raise AdapterError(
            "INVALID_REQUEST", "params.identity contains unsupported characters"
        )


def _retired_action_error(action: str) -> AdapterError:
    replacements = RETIRED_ACTION_REPLACEMENTS[action]
    return AdapterError(
        "UNSUPPORTED_ACTION",
        f"{action} has been retired; use one single-setting replacement action",
        {"action": action, "replacement_actions": replacements},
    )


def validate_action_params(action: str, params: Mapping[str, Any]) -> None:
    if action in RETIRED_ACTION_REPLACEMENTS:
        raise _retired_action_error(action)
    if action == "identities.query":
        if params:
            raise AdapterError(
                "INVALID_REQUEST", "identities.query does not accept parameters"
            )
    elif action == "identity.set_plain_text_signature":
        _reject_unexpected_fields(action, params, {"identity", "signature_text"})
        _validate_identity(params)
        if "signature_text" not in params:
            raise AdapterError("INVALID_REQUEST", "params.signature_text is required")
        if not isinstance(params["signature_text"], str):
            raise AdapterError(
                "INVALID_REQUEST", "params.signature_text must be a string"
            )
    elif action == "identity.set_reply_quoting":
        _reject_unexpected_fields(action, params, {"identity", "enabled"})
        _validate_identity(params)
        if not isinstance(params.get("enabled"), bool):
            raise AdapterError("INVALID_REQUEST", "params.enabled must be a boolean")
    elif action in {
        "filters.set_subfolder_application",
        "inbox.set_unified",
        "theme.set_dark_mode",
    }:
        _reject_unexpected_fields(action, params, {"enabled"})
        if not isinstance(params.get("enabled"), bool):
            raise AdapterError("INVALID_REQUEST", "params.enabled must be a boolean")
    elif action == "xulstore.update":
        _string_list(params, "keys")
        if "value" not in params:
            raise AdapterError("INVALID_REQUEST", "params.value is required")
    elif action == "folders.ensure_local":
        _string_list(params, "names")
    elif action == "filters.configure":
        validate_filter_configuration(params)
    elif action == "messages.export_eml":
        semantic_fields = {"folder_name", "output_dir"}
        legacy_fields = {"source", "destination"}
        unexpected = sorted(set(params).difference(semantic_fields | legacy_fields))
        if unexpected:
            raise AdapterError(
                "INVALID_REQUEST",
                f"messages.export_eml received unsupported parameters: {unexpected}",
            )
        uses_semantic_contract = bool(semantic_fields.intersection(params))
        uses_legacy_contract = bool(legacy_fields.intersection(params))
        if uses_semantic_contract == uses_legacy_contract:
            raise AdapterError(
                "INVALID_REQUEST",
                "messages.export_eml requires exactly one complete parameter pair: "
                "folder_name/output_dir or source/destination",
            )
        if uses_semantic_contract:
            _string(params, "folder_name")
            output_dir = _string(params, "output_dir")
            if not (output_dir.startswith("/") or output_dir.startswith("~/")):
                raise AdapterError(
                    "INVALID_REQUEST",
                    "params.output_dir must be an absolute or ~/ path",
                )
        else:
            _string(params, "source")
            _string(params, "destination")
    elif action == "contacts.export_csv":
        _string(params, "address_book")
        _string(params, "output_path")
    elif action == "messages.query":
        _string(params, "folder_name")
        allowed = {
            "folder_name",
            "limit",
            "select_from",
            "order",
            "sender_contains",
            "subject_contains",
            "after",
            "before",
            "has_attachments",
        }
        unexpected = sorted(set(params).difference(allowed))
        if unexpected:
            raise AdapterError(
                "INVALID_REQUEST",
                f"messages.query received unsupported parameters: {unexpected}",
            )
        if "limit" in params and (
            isinstance(params["limit"], bool)
            or not isinstance(params["limit"], int)
            or not 1 <= params["limit"] <= 500
        ):
            raise AdapterError(
                "INVALID_REQUEST", "params.limit must be an integer from 1 to 500"
            )
        if params.get("select_from", "latest") not in {"latest", "earliest"}:
            raise AdapterError(
                "INVALID_REQUEST", "params.select_from must be latest or earliest"
            )
        if params.get("order", "descending") not in {"ascending", "descending"}:
            raise AdapterError(
                "INVALID_REQUEST", "params.order must be ascending or descending"
            )
        for field in ("sender_contains", "subject_contains", "after", "before"):
            if field in params:
                _string(params, field)
        if "has_attachments" in params and not isinstance(
            params["has_attachments"], bool
        ):
            raise AdapterError(
                "INVALID_REQUEST", "params.has_attachments must be a boolean"
            )
    elif action == "attachments.save":
        _string(params, "folder_name")
        _string(params, "output_path")
        allowed = {
            "folder_name",
            "message_id",
            "mailbox_index",
            "attachment_name",
            "attachment_index",
            "output_path",
            "overwrite",
        }
        unexpected = sorted(set(params).difference(allowed))
        if unexpected:
            raise AdapterError(
                "INVALID_REQUEST",
                f"attachments.save received unsupported parameters: {unexpected}",
            )
        if not any(field in params for field in ("message_id", "mailbox_index")):
            raise AdapterError(
                "INVALID_REQUEST",
                "attachments.save requires message_id or mailbox_index from messages.query",
            )
        if "message_id" in params:
            _string(params, "message_id")
        for field in ("mailbox_index", "attachment_index"):
            if field in params and (
                isinstance(params[field], bool)
                or not isinstance(params[field], int)
                or params[field] < 0
            ):
                raise AdapterError(
                    "INVALID_REQUEST", f"params.{field} must be a non-negative integer"
                )
        if "attachment_name" in params:
            _string(params, "attachment_name")
        output_path = str(params["output_path"])
        if not output_path.startswith(("/", "~/")):
            raise AdapterError(
                "INVALID_REQUEST",
                "params.output_path must be absolute or begin with ~/",
            )
        if "overwrite" in params and not isinstance(params["overwrite"], bool):
            raise AdapterError("INVALID_REQUEST", "params.overwrite must be a boolean")
    elif action == "accounts.remove":
        _string(params, "email")
        if "hostname" in params:
            _string(params, "hostname")
    elif action == "compose.attach":
        _string(params, "subject")
        _string(params, "attachment_path")
    elif action == "compose.set_recipients":
        recipients = _string_list(params, "recipients")
        if len(recipients) > 100:
            raise AdapterError(
                "INVALID_REQUEST",
                "params.recipients must contain at most 100 addresses",
            )
        if len({item.strip().casefold() for item in recipients}) != len(recipients):
            raise AdapterError(
                "INVALID_REQUEST", "params.recipients must not contain duplicates"
            )
        if params.get("mode", "append") not in {"append", "replace"}:
            raise AdapterError(
                "INVALID_REQUEST", "params.mode must be append or replace"
            )
        if "subject" in params:
            _string(params, "subject")
        unexpected = sorted(set(params).difference({"recipients", "mode", "subject"}))
        if unexpected:
            raise AdapterError(
                "INVALID_REQUEST",
                f"compose.set_recipients received unsupported parameters: {unexpected}",
            )
    elif action == "ui.prefill_account_setup":
        _string(params, "full_name")
        _string(params, "email")
        _string(params, "password")


def _verification(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AdapterError("INVALID_REQUEST", "verify must be an array")
    checks = []
    for index, item in enumerate(value):
        check = _mapping(item, f"verify[{index}]")
        if check.get("type") not in VERIFY_TYPES:
            raise AdapterError(
                "INVALID_REQUEST", f"verify[{index}].type is unsupported"
            )
        checks.append(check)
    return checks


def parse_action_request(raw: Any) -> ActionRequest:
    data = _mapping(raw, "request")
    action = data.get("action")
    if action in RETIRED_ACTION_REPLACEMENTS:
        raise _retired_action_error(action)
    if action not in ACTIONS:
        raise AdapterError(
            "UNSUPPORTED_ACTION", "unsupported Thunderbird action", {"action": action}
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
        request_id,
        adapter,
        action,
        timeout_ms,
        params,
        _verification(data.get("verify")),
    )
