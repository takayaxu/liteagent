"""Instruction-only routing for parameterized VS Code configuration actions."""

from __future__ import annotations

import re


from vscode_adapter.atomic_settings import ATOMIC_SETTINGS

CONFIGURATION_ACTIONS = frozenset({*ATOMIC_SETTINGS, "diagnostics.configure",
                                   "explorer.set_exclusion", "keybindings.ensure"})

_EXPLICIT_SETTING_RE = re.compile(
    r"(?i)\b(?:debug|diffEditor|editor|extensions|files|git|http|javascript|python|"
    r"search|security|terminal|typescript|window|workbench)\.[A-Za-z][A-Za-z0-9.]*\b"
)


_FIELD_PATTERNS = {
    "focus_editor_on_break": r"focus|cursor",
    "inline_values": r"inline.*valu|variable.*inline",
    "internal_console": r"internal.*console|console.*open",
    "open_debug_view": r"debug.*view|run and debug",
    "show_breakpoints_in_overview_ruler": r"overview.*ruler",
    "show_inline_breakpoint_candidates": r"inline.*breakpoint|breakpoint.*candidate",
    "wrap_tabs": r"tab.*wrap|wrap.*tab",
    "word_wrap": r"word.*wrap|code.*wrapp|wrapp.*code",
    "word_wrap_column": r"column|line.*length",
    "minimap_enabled": r"minimap",
    "line_numbers": r"line.*number",
    "sticky_scroll_enabled": r"sticky.*scroll",
    "smooth_scrolling": r"smooth.*scroll",
    "render_whitespace": r"render.*whitespace",
    "auto_save": r"auto.*sav",
    "auto_save_delay_ms": r"delay|millisecond|\bms\b",
    "trim_trailing_whitespace": r"trailing.*whitespace",
    "insert_final_newline": r"insert.*newline|final.*newline",
    "trim_final_newlines": r"trim.*newline",
    "hot_exit": r"hot.*exit",
}


def _matching_settings(group: str, instruction: str) -> list[str]:
    return [action for action in ATOMIC_SETTINGS if action.startswith(group + ".set_")
            and re.search(_FIELD_PATTERNS[action.split(".set_", 1)[1]], instruction, re.I)]


def required_actions(domain: str, instruction: str) -> list[str]:
    if domain != "vs_code":
        return []

    if _EXPLICIT_SETTING_RE.search(instruction):
        keys = set(_EXPLICIT_SETTING_RE.findall(instruction))
        return [action for action, (key, _) in ATOMIC_SETTINGS.items() if key in keys]

    if re.search(r"(?i)\b(?:shortcut|keybinding|key\s+binding|hotkey)\b", instruction):
        return ["keybindings.ensure"]

    if re.search(
        r"(?i)\b(?:debug|debugger|debugging|breakpoint)\b", instruction
    ) and re.search(
        r"(?i)\b(?:break|console|cursor|editor|focus|inline|open|ruler|variable)\w*\b",
        instruction,
    ):
        return _matching_settings("debugging", instruction)

    if re.search(
        r"(?i)\b(?:diagnostic|error|report|severity|warning)\w*\b", instruction
    ) and re.search(
        r"(?i)\b(?:import|module|python|type|undefined|unused|variable)\w*\b",
        instruction,
    ):
        return ["diagnostics.configure"]

    if re.search(r"(?i)\b(?:explorer|file|folder)\w*\b", instruction) and re.search(
        r"(?i)\b(?:exclude|hide|hidden|show|visible)\w*\b",
        instruction,
    ):
        return ["explorer.set_exclusion"]

    if re.search(
        r"(?i)\b(?:auto\s*save|autosave|automatic\s+sav(?:e|ing)|final\s+newline|hot\s+exit|"
        r"trailing\s+whitespace|trim\s+final\s+newlines?)\b",
        instruction,
    ):
        return _matching_settings("files", instruction)

    if re.search(
        r"(?i)\b(?:line\s+numbers?|minimap|render\s+whitespace|smooth\s+scrolling|"
        r"sticky\s+scroll|tabs?\s+(?:wrap|wrapped|wrapping)|wrap\s+tabs?|"
        r"wrap\w*\b.{0,30}\btabs?|"
        r"word\s+wrap|code\s+wrapping|wrap(?:ping)?\s+(?:column|line)|line\s+length)\b",
        instruction,
    ):
        return _matching_settings("editor", instruction)

    return []


def stage_actions(
    domain: str, instruction: str, actions: list[str], events: list
) -> list[str]:
    required = required_actions(domain, instruction)
    if not required:
        return actions
    if any(
        event.executed
        and event.proposed.get("kind") == "adapter"
        and event.proposed.get("action") in required
        for event in events
    ):
        return actions
    return [action for action in actions if action in required]
