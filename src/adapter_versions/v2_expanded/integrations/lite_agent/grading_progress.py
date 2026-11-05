"""One evidence-based next step for grading source documents into an existing table.

No answers, grades, formulas, mutations, tool restrictions or completion decisions
are generated here. The model compares source answers and chooses every score.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote

from .answer_completion_progress import _call, _context
from .atomic_tool_surface import atomic_provider_surface
from .completion_policy import effective_canonical_action
from .notes_preservation import source_texts


def _path(value: Any) -> str:
    return unquote(str(value or '').removeprefix('file://'))


def _answers(text: str) -> list[str]:
    return re.findall(r'(?im)^.*?\banswer\b[^\w\n]*([A-Z])\s*$', text)


def _row_source(row: list, columns: list[int], sources: dict, keys: list[str]) -> list[tuple[str, str]]:
    identities = [str(v) for v in row[:min(columns)] if str(v).strip()]
    return [(path, value) for path, value in sources.items() if path not in keys
            and any(identity in value for identity in identities)]


def _observed_checks(original: dict, current: dict, sources: dict, keys: list[str],
                     columns: list[int]) -> dict:
    """Check observations; never produce replacement grades or formula arguments."""
    before = original.get('display_text', [])
    rows = current.get('display_text', [])
    addresses = current.get('cell_addresses', [])
    protected = []
    for i, row in enumerate(before[1:], 1):
        if all(str(v).strip() for v in row) and i < len(rows):
            for j, value in enumerate(row):
                if j < len(rows[i]) and str(rows[i][j]) != str(value):
                    protected.append({'cell': addresses[i][j], 'original': value,
                                      'actual': rows[i][j]})
    result = {'original_entry_changes': protected, 'checked_rows': [], 'issues': [],
              'unchecked_rows': [], 'meaning': 'Independent source/readback consistency checks, '
              'not model review decisions or task acceptance. No replacement grades are supplied.'}
    if len(keys) != 1 or keys[0] not in sources:
        return result
    key = _answers(sources[keys[0]])
    conventions = {True: set(), False: set()}
    for row in before[1:]:
        match = _row_source(row, columns, sources, keys)
        if len(match) != 1:
            continue
        answers = _answers(match[0][1])
        if len(answers) != len(key) or len(key) != len(columns):
            continue
        for col, a, b in zip(columns, answers, key):
            if col < len(row) and str(row[col]).strip():
                conventions[a == b].add(str(row[col]))
    if any(len(values) != 1 for values in conventions.values()):
        result['unchecked_rows'] = ['original examples do not establish an unambiguous marker convention']
        return result
    markers = {kind: next(iter(values)) for kind, values in conventions.items()}
    total_columns = [j for j, label in enumerate(before[0]) if re.search(r'(?i)total', str(label))]
    scales = set()
    for example in before[1:]:
        try:
            indicators = sum(float(example[c]) for c in columns)
            if indicators and len(total_columns) == 1:
                scales.add(float(example[total_columns[0]]) / indicators)
        except (ValueError, TypeError, IndexError):
            continue
    for i, row in enumerate(rows[1:], 1):
        if i >= len(before) or all(str(v).strip() for v in before[i]):
            continue
        match = _row_source(row, columns, sources, keys)
        if len(match) != 1 or len(_answers(match[0][1])) != len(key) or len(key) != len(columns):
            result['unchecked_rows'].append(i + 1)
            continue
        if any(not str(row[c]).strip() for c in columns):
            continue
        answers = _answers(match[0][1])
        issues = []
        for col, a, b in zip(columns, answers, key):
            if str(row[col]) != markers[a == b]:
                issues.append({'cell': addresses[i][col], 'actual': row[col],
                    'source_path': match[0][0], 'student_letter': a, 'reference_letter': b,
                    'reason': 'Readback marker contradicts the original example convention for these source letters; '
                              'check formula equality and both true/false branches.'})
        if len(scales) == 1 and len(total_columns) == 1:
            col = total_columns[0]
            try:
                if abs(float(row[col]) - sum(float(row[c]) for c in columns) * next(iter(scales))) > 1e-9:
                    issues.append({'cell': addresses[i][col], 'actual': row[col],
                        'reason': 'Readback total is inconsistent with the question indicators and original example scale; '
                                  'repair the model-authored total formula, do not hand-count.'})
            except (ValueError, TypeError, IndexError):
                issues.append({'cell': addresses[i][col], 'actual': row[col],
                               'reason': 'Total readback is not numeric; inspect the formula.'})
        result['checked_rows'].append(i + 1)
        result['issues'].extend(issues)
    return result


def model_progress(state: Any, tools: list[dict] | None = None) -> dict | None:
    text = state.instruction.lower()
    if not (state.domain == 'multi_apps' and 'student' in text and 'answer' in text
            and 'spreadsheet' in text and re.search(r'\b(?:grading|grade|scoring)\b', text)):
        return None
    tools = tools or []
    inspection = None
    table = None
    original_table = None
    table_step = write_step = save_step = 0
    saved_read_step = 0
    preview_step = open_step = inspect_step = 0
    discovered: list[str] = []
    complete_listing = False
    for event in state.events:
        if not event.executed or event.error or event.proposed.get('kind') != 'adapter':
            continue
        adapter, action, args = effective_canonical_action(event, state.domain)
        body = _context(event)
        if (action == 'desktop.open_path' and inspection
                and _path(args.get('path')) == _path(inspection.get('url'))):
            open_step = event.step
        if adapter == 'libreoffice_calc':
            if action == 'workbook.read_file':
                preview_step = event.step
            if action == 'workbook.inspect':
                inspection = body
                inspect_step = event.step
            if (action == 'workbook.read_file' and body.get('sheets')
                    and (not write_step or save_step >= write_step)):
                table = body['sheets'][0]
                if original_table is None:
                    original_table = table
                table_step = event.step
                if event.step > save_step > 0:
                    saved_read_step = event.step
            if action == 'range.read' and body.get('display_text'):
                # Only a full observed table replaces the full table snapshot.
                if table and body.get('range') == table.get('returned_range', table.get('used_range')):
                    table = {**table, **body}
                    table_step = event.step
            if action in {'range.write', 'range.write_block', 'cell.set_formula'}:
                write_step = event.step
            if action == 'workbook.save':
                save_step = event.step
        if action == 'filesystem.find':
            for item in body.get('matches', []):
                path = item.get('path')
                if (item.get('kind') == 'file' and isinstance(path, str)
                        and PurePosixPath(path).suffix.lower() in {'.docx', '.doc', '.odt', '.rtf'}
                        and path not in discovered):
                    discovered.append(path)
            if (args.get('name_patterns') == ['*'] and not body.get('truncated')
                    and not body.get('matches_omitted')):
                complete_listing = True
    sources = source_texts(state)
    target = _path(inspection.get('url')) if inspection else None
    progress: dict = {'target': target, 'discovered_source_paths': discovered,
        'complete_source_paths': list(sources),
        'source_protection': 'Answer key and student papers are READ ONLY. Never deduplicate, '
            'replace, clear, save or reformat them. Repeated answer letters are valid different questions.',
        'meaning': 'Actual observations and next-action hints, not computed grades or acceptance.'}

    def step(stage: str, instruction: str, adapter: str | None = None,
             action: str | None = None, params: dict | None = None) -> dict:
        progress.update(stage=stage, next_step=instruction)
        if adapter and action:
            call = _call(tools, adapter, action, params or {})
            if action == 'range.write' and params is None:
                routes = [route for tool in tools for route in
                    tool.get('function', {}).get('parameters', {}).get('x-allowed-routes', [])]
                latest = state.events[-1] if state.events else None
                just_searched = (latest is not None and latest.executed and not latest.error
                    and latest.proposed.get('arguments', {}).get('query') == 'libreoffice_calc range.write')
                if len(routes) > 1 and not just_searched and any(
                        t.get('function', {}).get('name') == 'tools_search' for t in tools):
                    call = {'name': 'tools_search', 'arguments': {'query': 'libreoffice_calc range.write'}}

            if action == 'range.write' and params is None and call.get('name') == 'adapter__adapter_call':
                call = {}  # Model must compare and supply all write values itself.
            if call.get('name') == 'adapter__adapter_call':
                _, bindings = atomic_provider_surface(tools)
                bound = [name for name, binding in bindings.items()
                         if binding.get('adapter') == adapter and binding.get('action') == action]
                if len(bound) == 1:
                    call = {'name': bound[0], 'arguments': params or {}}
            if call:
                if call['name'] == 'tools_search':
                    if action == 'document.read_file':
                        call['arguments']['query'] = 'libreoffice_writer document.read_file libreoffice_calc range.write'
                    progress['required_operation'] = adapter + '.' + action
                    progress['next_step'] = ('This turn ONLY call the exact tools_search query below. '
                        'Do not edit, guess grades or search for a grading macro. Next required operation: '
                        + adapter + '.' + action + '.')
                    progress['stage'] = 'discover_required_operation'
                progress['suggested_tool_call'] = call
        if progress['stage'] == 'discover_required_operation' or stage in {
                'read_live_target', 'save_target', 'read_saved_target', 'read_current_target',
                'open_editable_target', 'inspect_editable_target'}:
            for key in ('answer_key_source', 'current_student_source', 'current_row', 'table',
                        'raw_answer_pairs', 'original_graded_rows_to_preserve'):
                progress.pop(key, None)
        return progress

    if not inspection or not target:
        return step('inspect_target', 'Inspect the already open Calc workbook to learn its exact URL, '
                    'sheet and used range. Do not create a replacement workbook.',
                    'libreoffice_calc', 'workbook.inspect', {})
    sheet = inspection.get('active_sheet')
    progress['sheet'] = sheet
    if table is not None and table_step < write_step:
        return step('read_live_target', 'The previous write changed the LIVE Calc workbook, not the saved disk file. '
                    'Read the full LIVE range now; workbook.read_file would return stale empty cells until save. '
                    'Do not repeat the write.', 'libreoffice_calc', 'range.read',
                    {'sheet': sheet, 'range': table.get('returned_range', table.get('used_range'))})
    if table is None:
        return step('read_current_target', 'Read the saved/actual score table, including existing entries, '
                    'student identities and column headings. Read after each write before choosing another '
                    'row. A successful write alone does not verify correct scores.',
                    'libreoffice_calc', 'workbook.read_file', {'path': target, 'max_rows': 100, 'max_columns': 40})
    progress['table'] = table
    original_rows = original_table.get('display_text', []) if original_table else []
    original_addresses = original_table.get('cell_addresses', []) if original_table else []
    progress['original_graded_rows_to_preserve'] = [
        {'values': row, 'cell_addresses': original_addresses[i]}
        for i, row in enumerate(original_rows[1:], 1)
        if len(row) > 2 and all(str(v).strip() for v in row)]
    if not complete_listing:
        return step('list_all_sources', 'List ALL files in the observed workbook directory using name_patterns=["*"]. '
                    'Lowercase answer/key globs can omit case-sensitive filenames; previous hits are not '
                    'a complete source inventory. Use actual returned names, not guessed names.',
                    'os', 'filesystem.find', {'roots': [str(PurePosixPath(target).parent)],
                    'name_patterns': ['*'], 'kind': 'file', 'recursive': True, 'max_results': 100})
    keys = [path for path in discovered if re.search(r'(?i)(reference|answer.?key|solutions?)', PurePosixPath(path).stem)]
    pending = [p for p in keys + discovered if p not in sources]
    if pending:
        path = pending[0]
        progress.pop('table', None)
        return step('read_source', 'Read this actual source path now: ' + path + '. Keep sources unchanged. '
                    'Read-file does not activate a file and does not authorize a Writer edit. '
                    'Observe all questions, student identity and marked answers, including repeated letters. '
                    'Continue any truncated read before grading. Do not treat the existing graded row as the answer key.',
                    'libreoffice_writer', 'document.read_file', {'path': path, 'max_chars': 12000})
    if not keys:
        return step('identify_key', 'All listed documents have been read. Identify the actual reference '
                    'answers from source headings/content; do not invent a key or use one student as the key. '
                    'If the listing is incomplete, inspect the actual parent directory. Sources remain read only.')
    progress['answer_key_source'] = [{'path': p, 'text': sources[p]} for p in keys if p in sources]
    rows = table.get('display_text', [])
    addresses = table.get('cell_addresses', [])
    headers = rows[0] if rows else []
    score_columns = [i for i, value in enumerate(headers) if re.fullmatch(r'(?i)Q\s*\d+', str(value).strip())]
    if not score_columns or not addresses:
        return step('inspect_scoring_layout', 'Use the actual headers and example graded row to identify '
                    'question-score columns and total formula. Do not overwrite identity columns. '
                    'Read exact cell addresses if they are absent.', 'libreoffice_calc', 'range.read',
                    {'sheet': sheet, 'range': table.get('returned_range', table.get('used_range'))})
    checks = _observed_checks(original_table, table, sources, keys, score_columns)
    progress['source_readback_checks'] = checks
    if checks['original_entry_changes']:
        progress.pop('table', None)
        progress.pop('answer_key_source', None)
        return step('restore_original_entries', 'Restore ONLY the changed original entries listed in '
                    'source_readback_checks.original_entry_changes to their exact original values. '
                    'The user requested remaining students; provided graded entries must remain unchanged. '
                    'Do not re-grade the original student, read sources again, or change any other cells. '
                    'Use the observed sheet and addresses; then read the live table.',
                    'libreoffice_calc', 'range.write')
    pending_rows = [(i, row) for i, row in enumerate(rows[1:], 1)
                    if any(j < len(row) and str(row[j]).strip() == '' for j in score_columns)]
    repair_rows = [(i, row) for i, row in enumerate(rows[1:], 1)
                   if any(issue['cell'] in addresses[i] for issue in checks['issues'])]
    progress['remaining_rows_with_blank_scores'] = len(pending_rows)
    if repair_rows:
        pending_rows = repair_rows + [item for item in pending_rows if item not in repair_rows]

    if pending_rows:
        if open_step <= preview_step:
            return step('open_editable_target', 'All source documents are read. The earlier workbook.read_file '
                        'was a temporary disk preview and may have closed the live workbook. Open this '
                        'exact target for editing now; do not reread any sources or write yet.',
                        'os', 'desktop.open_path', {'path': target})
        if inspect_step < open_step:
            return step('inspect_editable_target', 'The target open was requested. Inspect the live Calc '
                        'document now to confirm its URL and exact sheet before writing. Open success '
                        'alone is not proof that the editable target is ready.',
                        'libreoffice_calc', 'workbook.inspect', {})
        index, row = pending_rows[0]
        progress['current_row'] = {'display_text': row, 'cell_addresses': addresses[index], 'headers': headers}
        identities = [str(value) for j, value in enumerate(row) if j < min(score_columns) and str(value).strip()]
        matches = [(p, value) for p, value in sources.items() if p not in keys
                   and any(identity in value for identity in identities)]
        progress['current_student_source'] = [{'path': p, 'text': value} for p, value in matches]
        if len(matches) == 1 and len(keys) == 1:
            key_answers = _answers(sources[keys[0]])
            student_answers = _answers(matches[0][1])
            if len(key_answers) == len(student_answers) == len(score_columns):
                progress['raw_answer_pairs'] = [
                    {'source_position': i + 1, 'column_header': headers[column],
                     'target_cell': addresses[index][column],
                     'reference_answer': key_answers[i], 'student_answer': student_answers[i]}
                    for i, column in enumerate(score_columns)]
                progress['pair_meaning'] = ('Verbatim marked source choices in occurrence order. '
                    'No equality judgments, scores or total are computed here. Check source order yourself.')
        progress['existing_graded_rows'] = [{'display_text': old, 'cell_addresses': addresses[i]}
            for i, old in enumerate(rows[1:], 1) if i != index and all(
                j < len(old) and str(old[j]).strip() for j in score_columns)]
        observed_values = sorted({str(old[j]) for old in original_table.get('display_text', [])[1:] for j in score_columns
            if j < len(old) and str(old[j]).strip()})
        total_columns = [i for i, header in enumerate(headers) if re.search(r'(?i)total', str(header))]
        progress['write_contract'] = {
            'sheet': sheet,
            'question_range': addresses[index][min(score_columns)] + ':' + addresses[index][max(score_columns)],
            'question_headers': [headers[j] for j in score_columns],
            'values_shape': 'TWO dimensional JSON array. Outer array contains exactly ONE row array. '
                'Row array contains typed comparison formula objects followed by the typed total formula object. '
                'Do not use address-keyed dictionaries, kind=text, quoted marker strings or one-dimensional values.',
            'row_cell_count': len(score_columns) + len(total_columns),
            'observed_existing_question_marker_values': observed_values,
            'total_cells': [addresses[index][j] for j in total_columns],
            'total_value_contract': 'The values element for a total cell MUST be a JSON object with '
                'kind equal to formula and value equal to your formula string. NOT a bare string.',
            'meaning': 'Copy sheet/address exactly. Select each indicator from existing marker convention; '
                'reference points weight belongs only in the total formula, not the question markers. '
                'Model authors all comparison values and the formula.'}
        progress.pop('table', None)
        return step('compare_one_student_and_write', 'WRITE ONE ROW. values MUST be a TWO-DIMENSIONAL array: [one_row_array]. '
                    'Every question cell MUST be a typed formula object (kind=formula,value=your formula). '
                    'Author an IF formula comparing ONLY the two actual raw_answer_pairs source letters '
                    'as QUOTED TEXT CONSTANTS, never the destination cell or any empty score cell. '
                    'Every formula value MUST start with =, followed by IF with exactly THREE arguments: '
                    'first the equality comparison between those two quoted letters, then the correct '
                    'marker, then the incorrect marker. Never pass each letter as a separate IF argument. '
                    'Use semicolons between IF arguments for Calc locale compatibility (commas cause508). '
                    'Equality TRUE must return the example’s correct marker and FALSE its incorrect marker. '
                    'Do not swap these branches when the two letters happen to differ. '
                    'Select the correct/incorrect return markers from the original example. '
                    'Do not manually judge letters or insert literal question scores. The total is also a typed formula. '
                    'Wrap the row in an extra outer array: values contains ONE ARRAY whose elements are '
                    'the typed objects. NOT a dictionary keyed by cell addresses, NOT kind=text, '
                    'NOT a one-dimensional list of objects. '
                    'Use one continuous rectangular range covering question cells through total, with '
                    'exactly write_contract.row_cell_count elements in that row. Copy write_contract.sheet. Each question marker is model-authored by comparing '
                    'the two raw_answer_pairs letters, using ONLY the original observed marker convention. '
                    'The TOTAL element in values MUST be an OBJECT with keys kind and value: '
                    'kind="formula", value=your SUM formula string over this row’s question cells times '
                    'reference-derived points. A bare formula string is WRONG: it writes text. '
                    'Include all question markers and this typed total object in one rectangular row write. '
                    'Pass only sheet, range and values inside params. Omit payload.verify entirely: '
                    'the following live range.read performs verification. Do not invent verification objects. '
                    'Preserve IDs, names and existing scored rows. Then read the live table.',
                    'libreoffice_calc', 'range.write')
    if write_step > save_step:
        progress.pop('answer_key_source', None)
        return step('save_target', 'All question-score cells are now populated in the observed table. '
                    'Save the target Calc workbook, then read it back; do not rewrite any sources.',
                    'libreoffice_calc', 'workbook.save', {})
    if save_step > saved_read_step:
        return step('read_saved_target', 'This turn ONLY execute the exact saved-file read in suggested_tool_call NOW. '
                    'Do not compare scores, recount answers, analyze totals, or plan corrections on this turn. '
                    'The file is saved; the next turn will contain the actual disk readback for review.', 'libreoffice_calc', 'workbook.read_file',
                    {'path': target, 'max_rows': 100, 'max_columns': 40})
    progress.pop('table', None)
    progress.pop('answer_key_source', None)
    progress['saved_read_step'] = saved_read_step
    progress['last_write_step'] = write_step
    return step('verify_completion', 'The saved table is already read back. Review ONLY the current '
                'source_readback_checks and original-entry preservation summary. Each checked row has '
                'already been compared with the actual source letters and original marker convention; '
                'this observation check does not establish unverified requirements. Do not restart a '
                'student-by-student mental recount, reread unchanged sources, or replace formulas with '
                'literal totals. If issues or unchecked_rows remain, address that specific evidence. '
                'If all requested rows, totals, preservation and saved destination are satisfied, submit '
                'propose_done now with the actual evidence. Do not invent a discrepancy by hand-counting.')
