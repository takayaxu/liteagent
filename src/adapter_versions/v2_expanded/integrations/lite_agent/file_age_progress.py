"""Keep time-based archive decisions grounded in the guest clock."""
import re
import shlex
from .completion_policy import effective_canonical_action


def model_progress(state):
    instruction = state.instruction
    age = re.search(r'last modified\s+(\d+)\s+days?\s+ago', instruction, re.I)
    if state.domain != 'os' or not age or not re.search(r'\bcompress\b', instruction, re.I):
        return None
    paths = re.findall(r'"(/[^"\n]+)"', instruction)
    root = paths[0] if paths else None
    inspected = []
    changed = []
    for event in state.events:
        if not event.executed or event.error:
            continue
        domain, action, params = effective_canonical_action(event, state.domain)
        if domain == 'os' and action == 'command.run':
            script = ' '.join(map(str, params.get('argv') or []))
            result = event.result or {}
            hint = result.get('context_hint', {})
            body = hint.get('downstream_context', hint)
            if 'date' in script and ('-mtime' in script or '-printf' in script):
                inspected.append({'step': event.step, 'stdout': body.get('stdout')})
            if any(word in script for word in ('gzip', 'tar ', ' mv ', 'zip ')):
                changed.append({'step': event.step, 'argv': params.get('argv'), 'stdout': body.get('stdout')})
    if not inspected:
        script = (f'date -Is; date -d "{age.group(1)} days ago" -Is; '
                  f'find {shlex.quote(root)} -type f -mtime {int(age.group(1))} -printf "%p %TY-%Tm-%Td %TH:%TM:%TS\\n"'
                  if root else None)
        return {'stage': 'inspect_guest_file_age', 'observed_paths_from_instruction': paths,
            'suggested_argv': ['bash', '-c', script] if script else None,
            'next_step': 'CURRENT STEP ONLY: use tools_search query="os command.run" if needed, '
                'then command.run with suggested_argv, cwd_source=home and provenance=shell_history. '
                'The guest clock and find -mtime determine which files match the requested age. '
                'Do not reject date labels by mental arithmetic or fail_task before this check. '
                'For exactly N days ago find -mtime N matches ages from N to N+1 days; '
                'use +N only if the user explicitly says older than N days.'}
    return {'stage': 'archive_and_verify_age_groups', 'guest_age_observations': inspected,
        'performed_commands': changed, 'next_step':
        'CURRENT STEP: use the real find age results above. Archive/compress matching source '
        'files into the requested old destination. If they are already there, compress them '
        'in place rather than moving the directory into itself. Other files go into the new '
        'destination; files already there can stay. Freeze source selection before creating '
        'archives so generated outputs are not recursively reprocessed. Do not include the '
        'old/new destination directories themselves. Use bash -c for shell syntax, and model '
        'selects the actual compression/move command from the observed files. After writing, '
        'inspect both final directories and test actual archive readability, then propose_done. '
        'Do not fail_task merely because a matching old file is already under old_files.'}
