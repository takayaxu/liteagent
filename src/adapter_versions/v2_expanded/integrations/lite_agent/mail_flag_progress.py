"""Guide live application checks for profile-backed mail flag changes."""
import re
import csv
import io
import subprocess
from difflib import SequenceMatcher
from PIL import Image


def model_progress(state, screenshot=None):
    if state.domain != 'thunderbird' or not re.search(r'\bstar\b', state.instruction, re.I):
        return None
    if not re.search(r'\b(every|all)\b.*\b(email|message)', state.instruction, re.I):
        return None
    match = re.search(r'\blocal\s+(.+?)\s+folder\b', state.instruction, re.I)
    target = match.group(1).strip(' `"') if match else None
    text = screen_text_observations(screenshot) if screenshot else []
    matches = [o for o in text if target and o['x'] < 360 and
               SequenceMatcher(None, o['text'].lower(), target.lower()).ratio() >= 0.72]
    target_box = min(matches, key=lambda o: o['x']) if matches else None
    gui = [e for e in state.events if e.executed and not e.error
           and e.proposed.get('tool') == 'gui_action']
    actions = [e.proposed.get('arguments', {}) for e in gui]
    folder_clicked = target_box and any(a.get('action') == 'click' and
        abs(int(a.get('x', -10000)) - target_box['x']) < 12 and
        abs(int(a.get('y', -10000)) - target_box['y']) < 12 for a in actions)
    if target_box and not folder_clicked:
        return {'stage': 'open_observed_folder', 'observed_folder_text': target_box,
            'suggested_tool_call': {'action': 'click',
                'fallback_reason': 'Mailbox-header updates do not synchronize live Thunderbird flags.',
                'x': target_box['x'], 'y': target_box['y']},
            'next_step': 'CURRENT STEP ONLY: call gui_action with the suggested_tool_call below. '
                'Its coordinates come from OCR of THIS screenshot in the 1280x720 model image. '
                'Do not reuse an older guessed coordinate or edit mailbox headers. '
                'After this click the next stage selects the visible message rows.'}
    focused = any(a.get('action') == 'press' and a.get('key', '').lower() == 'f6' for a in actions)
    selected = any(a.get('action') == 'hotkey' and a.get('keys') == ['ctrl', 'a'] for a in actions)
    starred = any(a.get('action') == 'press' and a.get('key', '').lower() == 's' for a in actions)
    if starred:
        if verified_live_mutation(state) is not None:
            return {'stage': 'complete_live_verified_stars', 'next_step':
                'CURRENT STEP: the real GUI star operation is followed by a full native query '
                'of the requested folder, with every message starred. Inspect the latest '
                'screenshot too; if all stars are filled, propose_done now. Do not toggle S again.'}
        return {'stage': 'read_back_live_stars', 'next_step':
            'CURRENT STEP ONLY: call messages.query for the exact requested folder with limit=500 '
            'to read back the flags after the real GUI star operation. Do not call propose_done '
            'yet. Compare returned_count with matched_count and verify every returned message '
            'has starred=true. Do not press S again or write mailbox files. The next stage '
            'will allow completion only after the full persisted readback.'}
    if selected:
        return {'stage': 'star_selected_messages', 'next_step':
            'CURRENT STEP ONLY: inspect the screenshot of the selected message rows. If some '
            'are unstarred, use gui_action press key="s" to add stars to the selected messages. '
            'Use fallback_reason="Profile-backed flags do not synchronize the live Thunderbird '
            'message index; perform the change through the application." Do not change folders.'}
    reason = 'Mailbox-header updates do not synchronize live Thunderbird flags.'
    if folder_clicked and not focused:
        return {'stage': 'focus_live_message_list', 'suggested_tool_call': {
            'action': 'press', 'fallback_reason': reason, 'key': 'f6'},
            'next_step': 'CURRENT STEP ONLY: call gui_action action=press key="f6" with the '
                'provided fallback_reason. The target folder was opened by the observed click; '
                'F6 moves focus from the folder tree into its message list. Do not call '
                'messages.update_flags or propose_done. Next stage selects all visible messages.'}
    if focused and not selected:
        return {'stage': 'select_all_live_messages', 'suggested_tool_call': {
            'action': 'hotkey', 'fallback_reason': reason, 'keys': ['ctrl', 'a']},
            'next_step': 'CURRENT STEP ONLY: call gui_action action=hotkey keys=["ctrl","a"] '
                'with the provided fallback_reason. F6 already focused the message list. '
                'Do not edit mailbox files or call propose_done. The next stage presses S.'}
    return {'stage': 'select_live_folder_messages', 'folder_already_clicked': bool(folder_clicked), 'next_step':
        'CURRENT STEP: perform the star operation in the live Thunderbird application. '
        'messages.update_flags edits mailbox headers but does not synchronize the running '
        'application index; its verification alone is insufficient. Use GUI fallback with this '
        'specific reason. From the current screenshot click the requested folder under the '
        'requested account (expand Local Folders if needed), ONLY if folder_already_clicked is false. '
        'When folder_already_clicked is true, skip the folder click. Inspect the new screenshot, then '
        'click a message row to focus the message list and use gui_action hotkey keys=["ctrl","a"] '
        'to select every message in THAT folder. Do not press Ctrl+A while the folder tree or '
        'search field is focused. The following stage will inspect stars and press S if needed. '
        'If the folder is already open and messages are visible, do NOT click the folder again; '
        'focus one actual message row, then Ctrl+A. Use observed screenshot text coordinates '
        'when provided, not coordinates recalled from a different image size. '
        'Do not edit profile files again or declare completion before checking the live stars.'}


def screen_text_observations(screenshot):
    """Read screenshot text boxes in exactly the model's pixel frame."""
    try:
        with Image.open(io.BytesIO(screenshot)) as image:
            image = image.convert('RGB')
            original_width, original_height = image.size
            scale = min(1280 / original_width, 720 / original_height, 1.0)
            buffer = io.BytesIO()
            image.save(buffer, format='PNG')
        result = subprocess.run(['tesseract', 'stdin', 'stdout', '--psm', '11', 'tsv'],
                                input=buffer.getvalue(), capture_output=True, timeout=8)
        if result.returncode:
            return []
        observations = []
        for row in csv.DictReader(io.StringIO(result.stdout.decode()), delimiter='\t'):
            text = row.get('text', '').strip()
            if text and float(row.get('conf', -1)) >= 45:
                observations.append({'text': text,
                    'x': round((int(row['left']) + int(row['width']) / 2) * scale),
                    'y': round((int(row['top']) + int(row['height']) / 2) * scale)})
        return observations[:250]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def verified_live_mutation(state):
    """Return an actual GUI star action only with full subsequent native proof."""
    if state.domain != 'thunderbird' or not re.search(
            r'\bstar\b.*\b(every|all)\b.*\b(email|message)', state.instruction, re.I):
        return None
    match = re.search(r'\blocal\s+(.+?)\s+folder\b', state.instruction, re.I)
    if not match:
        return None
    folder = match.group(1).strip(' `"').casefold()
    toggles = [e for e in state.events if e.executed and not e.error
               and e.proposed.get('tool') == 'gui_action'
               and e.proposed.get('arguments', {}).get('action') == 'press'
               and e.proposed.get('arguments', {}).get('key', '').lower() == 's']
    if not toggles:
        return None
    toggle = toggles[-1]
    from .completion_policy import effective_canonical_action

    for event in reversed(state.events):
        if not event.executed or event.error or event.step <= toggle.step:
            continue
        if event.proposed.get('tool') == 'gui_action':
            return None  # A later GUI operation invalidates the earlier readback.
        domain, action, params = effective_canonical_action(event, state.domain)
        if domain != 'thunderbird' or action != 'messages.query':
            continue
        hint = (event.result or {}).get('context_hint', {})
        observed = hint.get('downstream_context', hint)
        if not isinstance(observed, dict):
            observed = {}
        actual_folder = str(observed.get('folder', '')).rstrip('/').split('/')[-1].casefold()
        rows = observed.get('messages', [])
        count = observed.get('matched_count')
        if (actual_folder == folder and isinstance(count, int) and count > 0
                and observed.get('returned_count') == count and len(rows) == count
                and all(isinstance(row, dict) and row.get('starred') is True for row in rows)):
            return toggle
        return None
    return None
