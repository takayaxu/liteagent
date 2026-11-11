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
    probes = []
    for e in state.events:
        if not e.executed or e.error:
            continue
        domain, action, args = effective_canonical_action(e, state.domain)
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
        for body in iter_result_mappings(e.result):
            for check in (body.get('verification') or {}).get('checks', []):
                expected = check.get('expected_state') or {}
                if (check.get('type') == 'terminal_size' and check.get('passed') is True
                        and (not expected or (expected.get('columns') == columns and expected.get('rows') == rows))):
                    probes.append(e.step)
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
    if not any(step > max(launched) for step in probes):
        return {**base, 'stage': 'probe_new_default_size',
                'next_step': 'A new terminal has been opened. Search os command.run and call it with '
                'params argv=["true"], cwd_source="home", provenance="none"; attach a payload.verify '
                'check of type="terminal_size" using the requested columns/rows below. That existing '
                'verifier opens a fresh terminal and reads real stty size without a geometry override. '
                'Echoing the requested dimensions is not verification. If the check fails, inspect '
                'actual profile startup settings rather than claiming success.',
                'existing_verification_check': {'type': 'terminal_size', 'columns': columns, 'rows': rows}}
    return {**base, 'stage': 'review_verified_defaults',
            'next_step': 'Saved default preferences and actual fresh-terminal dimensions have been '
            'verified. Review the instruction and propose_done if no requirement remains. '
            'Do not repeat settings, print fabricated verification, or add a geometry override.'}
