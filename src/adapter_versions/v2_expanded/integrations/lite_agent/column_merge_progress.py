"""Guide command-line column concatenation and terminal application launch."""
import re
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
    merged = [c for c in commands if c['executed'] and not c['error']
              and c['params'].get('stdout_path') and 'paste' in ' '.join(c['params'].get('argv') or [])]
    if merged:
        output = merged[-1]['params']['stdout_path']
        launched = [c for c in commands if c['executed'] and not c['error']
            and c['params'].get('terminal') is True and output in (c['params'].get('argv') or [])]
        if launched:
            return {'stage': 'verify_open_csv', 'commands': commands[-8:], 'next_step':
                'CURRENT STEP: inspect the current screenshot and use Calc workbook.inspect '
                'to confirm the exact output CSV is open, one output column and all requested '
                'rows are present. If a CSV import dialog is visible, inspect the preview and '
                'confirm the appropriate encoding/separators before native inspection. '
                'Then propose_done; do not launch Calc again.'}
        return {'stage': 'open_csv_from_visible_terminal', 'commands': commands[-8:],
            'next_step': 'CURRENT STEP: read back the saved output CSV once and compare every '
                'row to the two original input CSV rows. Then use command.run to open the exact '
                'output_path in libreoffice --calc with terminal=true, cwd_source=home, '
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
