from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Any, Callable

from .command import CommandRunner
from .errors import AdapterError
from .filter_contract import compile_filter_configuration
from .profile import (
    ensure_local_folders,
    export_contacts_csv,
    export_folder_messages,
    export_mbox_messages,
    find_profile,
    query_identities,
    query_messages,
    remove_account,
    resolve_filter_rules_path,
    save_attachment,
    update_message_flags,
    update_json_path,
    update_preferences,
    write_filters,
)
from .schema import validate_action_params
from .ui import (
    compose_attachment,
    compose_set_recipients,
    prefill_account_setup,
)


def normalize_plain_text_line_breaks(value: str) -> str:
    """Accept common model-produced escaped line breaks as plain-text newlines."""
    return value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")


SEMANTIC_SETTING_ACTIONS = frozenset(
    {
        "identity.set_plain_text_signature",
        "identity.set_reply_quoting",
        "filters.set_subfolder_application",
        "inbox.set_unified",
        "theme.set_dark_mode",
    }
)


def semantic_preference_update(action: str, params: dict[str, Any]) -> dict[str, Any]:
    identity = str(params.get("identity", "")).strip()
    values: dict[str, Any] = {}
    remove_keys: list[str] = []
    if action == "identity.set_plain_text_signature":
        values[f"mail.identity.{identity}.htmlSigText"] = (
            normalize_plain_text_line_breaks(params["signature_text"])
        )
        values[f"mail.identity.{identity}.htmlSig"] = False
    elif action == "identity.set_reply_quoting":
        values[f"mail.identity.{identity}.auto_quote"] = params["enabled"]
    elif action == "filters.set_subfolder_application":
        enabled = params["enabled"]
        values["mail.server.default.applyIncomingFilters"] = enabled
        if enabled:
            values["mail.imap.use_status_for_biff"] = False
            remove_keys.append("mail.server.default.autosync_offline_stores")
    elif action == "theme.set_dark_mode":
        values["extensions.activeThemeID"] = (
            "firefox-compact-dark@mozilla.org"
            if params["enabled"]
            else "default-theme@mozilla.org"
        )
    return {"values": values, "remove_keys": remove_keys}


def semantic_xulstore_update(
    action: str, params: dict[str, Any]
) -> dict[str, Any] | None:
    if action != "inbox.set_unified":
        return None
    return {
        "keys": [
            "chrome://messenger/content/messenger.xhtml",
            "folderTree",
            "mode",
        ],
        "value": "smart" if params["enabled"] else "all",
    }


class ThunderbirdActions:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()

    def stop_thunderbird(self, timeout: float = 15) -> dict[str, Any]:
        before = self.runner.run(
            ["pgrep", "-x", "thunderbird"], check=False, timeout=5
        )["stdout"].split()
        self.runner.run(["pkill", "-TERM", "-x", "thunderbird"], check=False, timeout=5)
        deadline = time.monotonic() + min(timeout, 15)
        while time.monotonic() < deadline:
            running = self.runner.run(
                ["pgrep", "-x", "thunderbird"], check=False, timeout=5
            )["stdout"]
            if not running.strip():
                return {"stopped": True, "process_ids": before}
            time.sleep(0.2)
        self.runner.run(["pkill", "-KILL", "-x", "thunderbird"], check=False, timeout=5)
        time.sleep(0.5)
        return {"stopped": True, "process_ids": before, "forced": True}

    def start_thunderbird(self, timeout: float = 30) -> dict[str, Any]:
        command = shlex.join(["/usr/bin/thunderbird"])
        self.runner.run(
            [
                "bash",
                "-lc",
                f"nohup {command} >/tmp/osworld-thunderbird-adapter.log 2>&1 </dev/null &",
            ],
            timeout=5,
        )
        deadline = time.monotonic() + min(timeout, 45)
        observed = ""
        while time.monotonic() < deadline:
            observed = self.runner.run(["wmctrl", "-lx"], check=False, timeout=5)[
                "stdout"
            ]
            if "thunderbird" in observed.lower():
                return {
                    "started": True,
                    "windows": [
                        line
                        for line in observed.splitlines()
                        if "thunderbird" in line.lower()
                    ],
                }
            time.sleep(0.25)
        raise AdapterError(
            "APPLICATION_NOT_READY",
            "Thunderbird did not create a window",
            {"wmctrl": observed},
            503,
        )

    def activate(self) -> None:
        self.runner.run(["wmctrl", "-xa", "Mail.thunderbird"], check=False, timeout=5)
        time.sleep(0.3)

    def _profile_action(
        self, operation: Callable[[Path], dict[str, Any]], timeout: float
    ) -> dict[str, Any]:
        stopped = self.stop_thunderbird(min(timeout, 15))
        profile = find_profile()
        result = operation(profile)
        started = self.start_thunderbird(max(5, timeout - 15))
        return {
            **result,
            "profile": str(profile),
            "lifecycle": {"stop": stopped, "start": started},
        }

    @staticmethod
    def _require_known_identity(profile: Path, identity: str) -> None:
        discovered = query_identities(profile)["identities"]
        if identity not in {row["identity"] for row in discovered}:
            raise AdapterError(
                "IDENTITY_NOT_FOUND",
                f"Thunderbird identity does not exist: {identity}",
                {
                    "identity": identity,
                    "available_identities": discovered,
                    "correct_usage": (
                        "Call identities.query and use one exact returned identity value."
                    ),
                },
                404,
            )

    def _configure_semantic_setting(
        self, action: str, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        validate_action_params(action, params)
        preference_update = semantic_preference_update(action, params)
        xulstore_update = semantic_xulstore_update(action, params)
        profile = find_profile()
        if action.startswith("identity."):
            self._require_known_identity(profile, params["identity"].strip())
        stopped = self.stop_thunderbird(min(timeout, 15))
        preference_result = None
        if preference_update["values"] or preference_update["remove_keys"]:
            preference_result = update_preferences(
                profile / "prefs.js",
                preference_update["values"],
                preference_update["remove_keys"],
            )
        xulstore_result = None
        if xulstore_update is not None:
            xulstore_result = update_json_path(
                profile / "xulstore.json",
                xulstore_update["keys"],
                xulstore_update["value"],
            )
        started = self.start_thunderbird(max(5, timeout - 15))
        configured = dict(params)
        if action == "identity.set_plain_text_signature":
            configured["signature_text"] = normalize_plain_text_line_breaks(
                configured["signature_text"]
            )
        return {
            "action": action,
            "profile": str(profile),
            "preferences": preference_result,
            "xulstore": xulstore_result,
            "lifecycle": {"stop": stopped, "start": started},
            "configured": configured,
        }

    def identity_set_plain_text_signature(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        return self._configure_semantic_setting(
            "identity.set_plain_text_signature", params, timeout
        )

    def identity_set_reply_quoting(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        return self._configure_semantic_setting(
            "identity.set_reply_quoting", params, timeout
        )

    def filters_set_subfolder_application(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        return self._configure_semantic_setting(
            "filters.set_subfolder_application", params, timeout
        )

    def inbox_set_unified(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        return self._configure_semantic_setting("inbox.set_unified", params, timeout)

    def theme_set_dark_mode(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        return self._configure_semantic_setting("theme.set_dark_mode", params, timeout)

    def xulstore_update(self, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        return self._profile_action(
            lambda profile: update_json_path(
                profile / "xulstore.json", list(params["keys"]), params["value"]
            ),
            timeout,
        )

    def folders_ensure_local(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        return self._profile_action(
            lambda profile: ensure_local_folders(profile, params["names"]), timeout
        )

    def filters_configure(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        configuration = compile_filter_configuration(params)

        def operation(profile: Path) -> dict[str, Any]:
            path = resolve_filter_rules_path(profile)
            if configuration["local_folder"]:
                folder = (
                    profile / "Mail" / "Local Folders" / configuration["local_folder"]
                )
                if not folder.is_file():
                    raise AdapterError(
                        "LOCAL_FOLDER_NOT_FOUND",
                        "filter.destination local folder does not exist: "
                        f"{configuration['local_folder']}; call folders.ensure_local "
                        "with names=[destination] before filters.configure",
                        http_status=404,
                    )
            return write_filters(path, configuration["filter"])

        return self._profile_action(operation, timeout)

    def messages_export_eml(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        validate_action_params("messages.export_eml", params)
        if "folder_name" in params:
            return self._profile_action(
                lambda profile: export_folder_messages(
                    profile,
                    params["folder_name"],
                    Path(params["output_dir"]).expanduser(),
                ),
                timeout,
            )
        return self._profile_action(
            lambda profile: export_mbox_messages(
                profile / params["source"], Path(params["destination"]).expanduser()
            ),
            timeout,
        )

    def contacts_export_csv(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        return self._profile_action(
            lambda profile: export_contacts_csv(
                profile,
                params["address_book"],
                Path(params["output_path"]),
            ),
            timeout,
        )

    def messages_query(self, params: dict[str, Any], _timeout: float) -> dict[str, Any]:
        profile = find_profile()
        return {
            **query_messages(
                profile,
                params["folder_name"],
                limit=params.get("limit", 50),
                select_from=params.get("select_from", "latest"),
                order=params.get("order", "descending"),
                sender_contains=params.get("sender_contains"),
                subject_contains=params.get("subject_contains"),
                after=params.get("after"),
                before=params.get("before"),
                has_attachments=params.get("has_attachments"),
            ),
            "profile": str(profile),
        }

    def identities_query(
        self, _params: dict[str, Any], _timeout: float
    ) -> dict[str, Any]:
        profile = find_profile()
        return {**query_identities(profile), "profile": str(profile)}

    def attachments_save(
        self, params: dict[str, Any], _timeout: float
    ) -> dict[str, Any]:
        profile = find_profile()
        return {
            **save_attachment(
                profile,
                params["folder_name"],
                Path(params["output_path"]),
                message_id=params.get("message_id"),
                mailbox_index=params.get("mailbox_index"),
                attachment_name=params.get("attachment_name"),
                attachment_index=params.get("attachment_index"),
                overwrite=params.get("overwrite", False),
            ),
            "profile": str(profile),
        }

    def accounts_remove(self, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        return self._profile_action(
            lambda profile: remove_account(
                profile, params["email"], params.get("hostname")
            ),
            timeout,
        )

    def compose_attach(self, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.runner.run(
            ["wmctrl", "-a", f"Write: {params['subject']} - Thunderbird"],
            check=False,
            timeout=5,
        )
        return compose_attachment(params["subject"], params["attachment_path"], timeout)

    def compose_set_recipients(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        return compose_set_recipients(
            params["recipients"],
            params.get("mode", "append"),
            params.get("subject"),
            timeout,
        )

    def ui_prefill_account_setup(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        self.activate()
        return prefill_account_setup(
            params["full_name"], params["email"], params["password"], timeout
        )

    def dispatch(
        self, action: str, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        if action == "mail.configure":
            raise AdapterError(
                "UNSUPPORTED_ACTION",
                "mail.configure has been retired; use one single-setting replacement action",
                {
                    "action": action,
                    "replacement_actions": sorted(SEMANTIC_SETTING_ACTIONS),
                },
            )
        method = getattr(self, action.replace(".", "_"), None)
        if method is None:
            raise AdapterError(
                "UNSUPPORTED_ACTION",
                "unsupported Thunderbird action",
                {"action": action},
            )
        return method(params, timeout)


    def messages_update_flags(
        self, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        return self._profile_action(
            lambda profile: update_message_flags(
                profile,
                params["folder_name"],
                mailbox_indices=params["mailbox_indices"],
                flag=params["flag"],
                value=params["value"],
            ),
            timeout,
        )
