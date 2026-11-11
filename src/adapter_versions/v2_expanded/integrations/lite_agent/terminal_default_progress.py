"""Prompt-only progress for persistent terminal character dimensions."""
import re
from .completion_policy import effective_canonical_action
from .result_envelopes import iter_result_mappings


def model_progress(state):
    size = re.search(r'\b(\d{2,3})\s*[x×]\s*(\d{1,3})\b', state.instruction)
    if (state.domain != 'os' or not size or not re.search(r'terminal', state.instruction, re.I)
            or not re.search(r'permanent|default|reboot|startup', state.instruction, re.I)):
        return None
    columns, rows = map(int, size.groups())
    requested = {'default-size-columns': columns, 'default-size-rows': rows}
    observed = {}
    writes = []
    launched = []
    typed_probe = []
    submitted_probe = []
    for e in state.events:
        if not e.executed or e.error:
            continue
        domain, action, args = effective_canonical_action(e, state.domain)
        if e.proposed.get('kind') == 'gui':
            gui_args = e.proposed.get('arguments', {})
            if gui_args.get('action') == 'type' and gui_args.get('text', '').strip() == 'stty size':
                typed_probe.append(e.step)
            if gui_args.get('action') == 'press' and gui_args.get('key') in {'enter', 'Return', 'Enter'} and typed_probe:
                submitted_probe.append(e.step)
        if domain != 'os':
            continue
        if action in {'terminal.default_profile.inspect', 'terminal.default_profile.set_setting'}:
            for body in iter_result_mappings(e.result):
                if body.get('key') in requested and 'value' in body:
                    observed[body['key']] = body['value']
            if action.endswith('set_setting'):
                writes.append(e.step)
        if action == 'terminal.launch':
            launched.append(e.step)
    base = {'requested_character_dimensions': {'columns': columns, 'rows': rows},
            'observed_saved_defaults': observed,
            'meaning': 'Prompt guidance from actual receipts, not completion or an evaluator result.'}
    pending = [key for key, value in requested.items() if observed.get(key) != value]
    if pending:
        key = pending[0]
        return {**base, 'stage': 'write_one_default',
                'next_step': 'Change the saved default profile, not the current window geometry. '
                'Inspect the default profile if its keys are unknown; then call '
                'terminal.default_profile.set_setting for only the next key and integer value below. '
                'Do not change the font, maximize a window, or print a success message.',
                'next_setting': {'key': key, 'value': requested[key]}}
    last_write = max(writes, default=0)
    if not any(step > last_write for step in launched):
        return {**base, 'stage': 'open_new_terminal',
                'next_step': 'Both saved dimensions have been read back. Now search os terminal.launch '
                'and call it with argv=["bash"]. This opens an actual new terminal using the saved '
                'defaults. Do not pass a geometry override. Do not propose_done or use echo as a size check.'}
    if not any(step > max(launched) for step in typed_probe):
        return {**base, 'stage': 'type_real_tty_probe',
                'next_step': 'The new terminal has focus. Use gui_action type with text="stty size". '
                'A background command.run has no terminal input and cannot run stty. '
                'This visible shell command checks actual rows and columns, not requested settings. '
                'Use GUI fallback because the direct command tool cannot access this terminal TTY.'}
    if not any(step > max(typed_probe) for step in submitted_probe):
        return {**base, 'stage': 'submit_real_tty_probe',
                'next_step': 'Use gui_action press key="enter" to run the typed stty size command. '
                'Then read its real output in the next screenshot.'}
    return {**base, 'stage': 'review_actual_tty_output',
            'next_step': 'Read the latest terminal screenshot: stty prints ROWS then COLUMNS. '
            'Compare that actual output with the requested dimensions. If it matches and saved '
            'defaults are correct, propose_done with the observed evidence. If it differs, inspect '
            'the startup settings and correct the cause; do not change font or force a one-window '
            'geometry as a substitute for persistent defaults. This stage does not assert success.'}
