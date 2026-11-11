"""Guide live application checks for profile-backed mail flag changes."""
import re


def model_progress(state):
    if state.domain != 'thunderbird' or not re.search(r'\bstar\b', state.instruction, re.I):
        return None
    if not re.search(r'\b(every|all)\b.*\b(email|message)', state.instruction, re.I):
        return None
    gui = [e for e in state.events if e.executed and not e.error
           and e.proposed.get('tool') == 'gui_action']
    actions = [e.proposed.get('arguments', {}) for e in gui]
    selected = any(a.get('action') == 'hotkey' and a.get('keys') == ['ctrl', 'a'] for a in actions)
    starred = any(a.get('action') == 'press' and a.get('key', '').lower() == 's' for a in actions)
    if starred:
        return {'stage': 'verify_live_stars', 'next_step':
            'CURRENT STEP: inspect the latest Thunderbird screenshot. Verify every message in '
            'the requested folder has a filled star. Do not press S again if they are filled, '
            'because S toggles. Wait briefly for Thunderbird to persist/index the change, then '
            'propose_done if all messages are starred. Correct only any remaining unstarred rows.'}
    if selected:
        return {'stage': 'star_selected_messages', 'next_step':
            'CURRENT STEP ONLY: inspect the screenshot of the selected message rows. If some '
            'are unstarred, use gui_action press key="s" to add stars to the selected messages. '
            'Use fallback_reason="Profile-backed flags do not synchronize the live Thunderbird '
            'message index; perform the change through the application." Do not change folders.'}
    return {'stage': 'select_live_folder_messages', 'next_step':
        'CURRENT STEP: perform the star operation in the live Thunderbird application. '
        'messages.update_flags edits mailbox headers but does not synchronize the running '
        'application index; its verification alone is insufficient. Use GUI fallback with this '
        'specific reason. From the current screenshot click the requested folder under the '
        'requested account (expand Local Folders if needed). Inspect the new screenshot, then '
        'click a message row to focus the message list and use gui_action hotkey keys=["ctrl","a"] '
        'to select every message in THAT folder. Do not press Ctrl+A while the folder tree or '
        'search field is focused. The following stage will inspect stars and press S if needed. '
        'Do not edit profile files again or declare completion before checking the live stars.'}
