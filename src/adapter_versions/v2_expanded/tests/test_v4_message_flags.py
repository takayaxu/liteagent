from pathlib import Path
import mailbox
from email.message import EmailMessage
import pytest
import jsonschema
from thunderbird_adapter.errors import AdapterError as ThunderbirdAdapterError
from thunderbird_adapter.profile import query_messages, update_message_flags
from thunderbird_adapter.verifier import verify_check
from thunderbird_adapter.schema import validate_action_params as validate_thunderbird
from integrations.lite_agent.tool_catalog import build_tools
DOWNSTREAM_ACTION = "attachments.save"


def _message(
    subject: str,
    *,
    message_id: str | None = None,
    attachment_name: str | None = None,
    mozilla_status: str | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = "sender@example.test"
    message["To"] = "recipient@example.test"
    message["Subject"] = subject
    message["Date"] = "Tue, 01 Jan 2030 00:00:00 +0000"
    if mozilla_status is not None:
        message["X-Mozilla-Status"] = mozilla_status
    if message_id is not None:
        message["Message-ID"] = f"<{message_id}>"
    message.set_content("synthetic message body")
    if attachment_name is not None:
        message.add_attachment(
            b"synthetic attachment payload",
            maintype="application",
            subtype="octet-stream",
            filename=attachment_name,
        )
    return message


def _profile_with_messages(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    mailbox_dir = profile / "Mail" / "Local Folders"
    mailbox_dir.mkdir(parents=True)
    box = mailbox.mbox(mailbox_dir / "Archive")
    try:
        box.add(_message("missing selector", attachment_name="missing.bin"))
        box.add(
            _message(
                "stable selector",
                message_id="stable@example.test",
                attachment_name="stable.bin",
                mozilla_status="0001",
            )
        )
        box.flush()
    finally:
        box.close()
    return profile


def _exposed_schema(action: str = DOWNSTREAM_ACTION) -> dict:
    tools = build_tools(
        "thunderbird",
        [action],
        include_gui=False,
        include_control_tools=False,
        strict_generic=True,
    )
    return tools[0]["function"]["parameters"]


def test_folder_flag_update_uses_observed_indices_and_reads_back(tmp_path: Path) -> None:
    profile = _profile_with_messages(tmp_path)
    query = query_messages(profile, "Archive", limit=500)
    assert query["matched_count"] == query["returned_count"] == 2
    rows = {item["mailbox_index"]: item for item in query["messages"]}
    assert rows[0]["starred"] is False
    assert rows[1]["starred"] is False

    updated = update_message_flags(
        profile,
        "Archive",
        mailbox_indices=[0, 1],
        flag="starred",
        value=True,
    )
    assert updated["verification_passed"] is True
    assert updated["changed_count"] == 2
    assert updated["after"] == {0: True, 1: True}
    assert verify_check(
        {
            "type": "message_flags",
            "profile": str(profile),
            "folder_name": "Archive",
            "mailbox_indices": [0, 1],
            "flag": "starred",
            "value": True,
        }
    )["passed"]

    # A different Mozilla status bit survives setting and clearing the star.
    box = mailbox.mbox(profile / "Mail" / "Local Folders" / "Archive", create=False)
    try:
        assert int(box[1]["X-Mozilla-Status"], 16) & 0x0001
    finally:
        box.close()
    cleared = update_message_flags(
        profile,
        "Archive",
        mailbox_indices=[1],
        flag="starred",
        value=False,
    )
    assert cleared["verification_passed"] is True
    box = mailbox.mbox(profile / "Mail" / "Local Folders" / "Archive", create=False)
    try:
        assert int(box[1]["X-Mozilla-Status"], 16) == 0x0001
    finally:
        box.close()


def test_folder_flag_update_contract_is_typed_and_bounded() -> None:
    action = "messages.update_flags"
    arguments = {
        "folder_name": "Bills",
        "mailbox_indices": [0, 1],
        "flag": "starred",
        "value": True,
    }
    exposed = _exposed_schema(action)
    jsonschema.Draft202012Validator.check_schema(exposed)
    assert not list(jsonschema.Draft202012Validator(exposed).iter_errors(arguments))
    validate_thunderbird(action, arguments)
    with pytest.raises(ThunderbirdAdapterError, match="unique"):
        validate_thunderbird(
            action,
            {**arguments, "mailbox_indices": [0, 0]},
        )
