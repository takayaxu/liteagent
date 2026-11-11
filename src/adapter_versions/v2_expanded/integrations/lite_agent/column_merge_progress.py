"""Guide command-line column concatenation and terminal application launch."""
import re
import posixpath
import shlex
from .completion_policy import effective_canonical_action


def model_progress(state):
    if not (state.domain == 'multi_apps' and re.search(r'command line', state.instruction, re.I)
            and re.search(r'concatenat', state.instruction, re.I)
            and re.search(r'columns?', state.instruction, re.I)):
        return None
    commands = []
    for event in state.events:
        adapter, action, params = effective_canonical_action(event, state.domain)
        if adapter == 'os' and action == 'command.run':
            hint = (event.result or {}).get('context_hint', {})
            body = hint.get('downstream_context', hint)
            commands.append({'step': event.step, 'params': params,
                'executed': event.executed, 'error': event.error,
                'stdout': body.get('stdout'), 'returncode': body.get('returncode')})
    merged = []
    for c in commands:
        argv = c['params'].get('argv') or []
        if not c['executed'] or c['error'] or 'paste' not in ' '.join(argv):
            continue
        output = c['params'].get('stdout_path')
        if len(argv) >= 3 and argv[:2] == ['bash', '-c']:
            tokens = shlex.split(argv[2])
            if '>' in tokens and tokens.index('>') + 1 < len(tokens):
                output = tokens[tokens.index('>') + 1]
        if output:
            if not output.startswith('/'):
                cwd = c['params'].get('cwd_path') if c['params'].get('cwd_source') == 'explicit' else None
                if not cwd:
                    continue
                output = posixpath.join(cwd, output)
            merged.append({**c, 'actual_output': output})
    if merged:
        output = merged[-1]['actual_output']
        launched = [c for c in commands if c['executed'] and not c['error']
            and c['params'].get('terminal') is True and output in (c['params'].get('argv') or [])]
        if launched:
            import_confirmed = any(e.executed and not e.error and e.step > launched[-1]['step']
                and e.proposed.get('tool') == 'gui_action'
                and e.proposed.get('arguments', {}).get('action') == 'press'
                and e.proposed.get('arguments', {}).get('key') == 'enter' for e in state.events)
            if not import_confirmed:
                return {'stage': 'confirm_csv_import',
                    'suggested_tool_call': {'action': 'press', 'key': 'enter',
                        'fallback_reason': 'Confirm the visible CSV import preview.'},
                    'next_step': 'CURRENT STEP ONLY: the file has been merged and launched. '
                        'Inspect the current import preview. When it displays the concatenated '
                        'strings as one column, call gui_action with suggested_tool_call exactly: '
                        'action=press, key=enter. Do not press Tab or change separator checkboxes '
                        'when the preview is already correct; a checked delimiter absent from '
                        'the data does not split the data. Enter confirms the dialog default OK. '
                        'No further command-line merge, conversion or launch is needed. '
                        'If the dialog is absent, inspect native Calc state instead.'}
            return {'stage': 'verify_open_csv', 'commands': commands[-8:], 'next_step':
                'CURRENT STEP ONLY: use tools_search query="libreoffice_calc workbook.inspect" if not exposed, '
                'then call that read-only inspection to confirm the current screenshot and '
                'to confirm the exact output CSV is open, one output column and all requested '
                'rows are present. If a CSV import dialog is visible, inspect the preview and '
                'confirm the appropriate encoding/separators before native inspection. '
                'Then propose_done; do not launch Calc again.'}
        return {'stage': 'open_csv_from_visible_terminal', 'commands': commands[-8:],
            'actual_output': output,
            'suggested_launch': {'adapter': 'os', 'action': 'command.run', 'payload': {'params': {
                'argv': ['libreoffice', '--calc', output], 'terminal': True,
                'cwd_source': 'home', 'provenance': 'shell_history'}}},
            'next_step': 'CURRENT STEP: read back the saved output CSV once and compare every '
                'row to the two original input CSV rows. Then use command.run to open the exact '
                'actual_output ABSOLUTE path in libreoffice --calc with terminal=true, cwd_source=home, '
                'provenance=shell_history. A visible terminal gives the requested terminal '
                'execution. Do not run the GUI launch synchronously or replace it with '
                'desktop.open_path. After launch inspect screenshot/native Calc state.'}
    return {'stage': 'prepare_and_merge_columns', 'commands': commands[-8:], 'next_step':
        'CURRENT STEP: use command.run with shell_history provenance for the requested workflow. '
        'Convert each observed input spreadsheet to CSV using libreoffice --headless --convert-to '
        'csv; inspect both CSVs completely and pair rows in their original order. '
        'To concatenate with NO separator, use argv=["bash","-c",<one complete shell script>] '
        'and paste -d \"\" <first CSV> <second CSV>, setting stdout_path to the requested output CSV. '
        'Direct argv currently rejects an empty string argument: that is a transport constraint, '
        'not permission to insert a space or another delimiter. Put the empty delimiter inside '
        'the explicit shell script. Preserve actual CSV quoting and verify every output row. '
        'After saving the next stage reads output and launches Calc with terminal=true.'}
