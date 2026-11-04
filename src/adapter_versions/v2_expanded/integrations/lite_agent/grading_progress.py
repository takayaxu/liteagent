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
from .completion_policy import effective_canonical_action
from .notes_preservation import source_texts


def _path(value: Any) -> str:
    return unquote(str(value or '').removeprefix('file://'))


def model_progress(state: Any, tools: list[dict] | None = None) -> dict | None:
    text = state.instruction.lower()
    if not (state.domain == 'multi_apps' and 'student' in text and 'answer' in text
            and 'spreadsheet' in text and re.search(r'\b(?:grading|grade|scoring)\b', text)):
        return None
    tools = tools or []
    inspection = None
    table = None
    table_step = write_step = save_step = 0
    saved_read_step = 0
    discovered: list[str] = []
    complete_listing = False
    for event in state.events:
        if not event.executed or event.error or event.proposed.get('kind') != 'adapter':
            continue
        adapter, action, args = effective_canonical_action(event, state.domain)
        body = _context(event)
        if adapter == 'libreoffice_calc':
            if action == 'workbook.inspect':
                inspection = body
            if (action == 'workbook.read_file' and body.get('sheets')
                    and (not write_step or save_step >= write_step)):
                table = body['sheets'][0]
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
            if action == 'range.write' and params is None and call.get('name') == 'adapter__adapter_call':
                call = {}  # Model must compare and supply all write values itself.
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
        if progress['stage'] == 'discover_required_operation':
            for key in ('answer_key_source', 'current_student_source', 'current_row', 'table'):
                progress.pop(key, None)
        return progress

    if not inspection or not target:
        return step('inspect_target', 'Inspect the already open Calc workbook to learn its exact URL, '
                    'sheet and used range. Do not create a replacement workbook.',
                    'libreoffice_calc', 'workbook.inspect', {})
    sheet = inspection.get('active_sheet')
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
    pending_rows = [(i, row) for i, row in enumerate(rows[1:], 1)
                    if any(j < len(row) and str(row[j]).strip() == '' for j in score_columns)]
    progress['remaining_rows_with_blank_scores'] = len(pending_rows)
    if pending_rows:
        index, row = pending_rows[0]
        progress['current_row'] = {'display_text': row, 'cell_addresses': addresses[index], 'headers': headers}
        identities = [str(value) for j, value in enumerate(row) if j < min(score_columns) and str(value).strip()]
        matches = [(p, value) for p, value in sources.items() if p not in keys
                   and any(identity in value for identity in identities)]
        progress['current_student_source'] = [{'path': p, 'text': value} for p, value in matches]
        def marked_answers(value: str) -> list[str]:
            return re.findall(r'(?im)^.*?\banswer\b[^\w\n]*([A-Z])\s*$', value)

        if len(matches) == 1 and len(keys) == 1:
            key_answers = marked_answers(sources[keys[0]])
            student_answers = marked_answers(matches[0][1])
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
        progress.pop('table', None)
        return step('compare_one_student_and_write', 'Work ONLY on current_row. Match its ID/name to '
                    'current_student_source. Compare each marked answer with the same question in '
                    'answer_key_source, in source order; do not solve the exam again. Derive scoring '
                    'units from the reference heading and existing graded example: per-question '
                    'indicators and total points use different units when the example shows this. '
                    'For each raw_answer_pairs position compare the TWO LETTERS exactly; do not conflate '
                    'neighboring questions. Use the example’s per-question indicator convention, then '
                    'compute total POINTS by applying the reference’s points per correct question. '
                    'A count of correct questions is not a points total. Check the same rule reproduces '
                    'the existing graded example. Calculate every score and total yourself, then range.write only this row’s blank '
                    'score cells and total using the exact observed addresses. Preserve completed '
                    'rows, IDs, names and formatting. No Writer editing, no source cleanup, no duplicate insertion.',
                    'libreoffice_calc', 'range.write')
    if write_step > save_step:
        progress.pop('answer_key_source', None)
        return step('save_target', 'All question-score cells are now populated in the observed table. '
                    'Save the target Calc workbook, then read it back; do not rewrite any sources.',
                    'libreoffice_calc', 'workbook.save', {})
    if save_step > saved_read_step:
        return step('read_saved_target', 'Read the saved score table once and verify all rows, original '
                    'entries, per-question comparisons and totals.', 'libreoffice_calc', 'workbook.read_file',
                    {'path': target, 'max_rows': 100, 'max_columns': 40})
    progress['student_source_review'] = [{'path': p, 'observed_identity_and_answer_lines': [
        line for line in value.splitlines() if re.search(r'(?i)student|\banswer\b', line)]}
        for p, value in sources.items() if p not in keys]
    return step('verify_completion', 'The saved table has been fully read back and no question-score '
                'blanks remain. This is coverage, not proof of correct grading. Compare every score '
                'with the actual student and reference answers, verify totals and preserved original '
                'rows. Only if all user requirements are satisfied submit propose_done. Do not reread '
                'the same sources or repeat writes without a concrete discrepancy.')
