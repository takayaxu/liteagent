"""Prompt facts for splitting a PDF while following an existing naming example."""
import re
from .completion_policy import effective_canonical_action
from .result_envelopes import iter_result_mappings


def model_progress(state):
    if not re.search(r'chapter', state.instruction, re.I) or not re.search(r'PDF', state.instruction, re.I) or not re.search(r'name|naming|example', state.instruction, re.I):
        return None
    files = []
    outlines = []
    writes = []
    for e in state.events:
        if not e.executed or e.error:
            continue
        domain, action, args = effective_canonical_action(e, state.domain)
        if domain != 'os':
            continue
        if action == 'filesystem.find':
            for body in iter_result_mappings(e.result):
                for f in body.get('matches', []):
                    if f.get('path') and f.get('path') not in files:
                        files.append(f['path'])
        if action == 'pdf.outline.inspect':
            for body in iter_result_mappings(e.result):
                if body.get('sections') and not outlines:
                    outlines.append({k: body.get(k) for k in ['input_path','source_page_count','prefix_page_count','sections','truncated']})
        if action == 'pdf.pages.extract':
            writes.append({'step': e.step, **args})
    base = {'observed_pdf_paths': files, 'observed_outline': outlines, 'executed_extractions': writes,
            'meaning': 'Facts from successful reads and extractions; no claim that the output set is correct.'}
    if not files:
        return {**base, 'stage': 'read_naming_example', 'next_step': 'Search os filesystem.find and list the book directory PDFs. '
                'Read the complete filename of the existing chapter example before selecting any output_path.'}
    if not outlines:
        return {**base, 'stage': 'read_chapter_boundaries', 'next_step': 'Search os pdf.outline.inspect and inspect the full book, '
                'not the already split chapter. Use the internal outline to observe chapter titles and physical inclusive page ranges.'}
    return {**base, 'stage': 'extract_with_observed_names', 'next_step': 'Compare the existing chapter filename above with its '
            'matching outline index/title to infer the requested naming pattern. Reuse that exact punctuation, spacing and title '
            'style for each remaining chapter; do not invent generic chapter N.pdf names if the example uses index and title. '
            'Keep the existing example and original book. Use each observed inclusive start_page/end_page directly, without adding '
            'a printed-page offset. Call pdf.pages.extract separately for one remaining chapter, choosing its output_path yourself. '
            'Skip chapters already present under the correct name and compare the complete final listing against the outline. '
            'Do not propose_done until every remaining chapter exists and no mistaken task-created duplicate filenames remain. '
            'A successful extraction does not validate the chosen filename.'}
