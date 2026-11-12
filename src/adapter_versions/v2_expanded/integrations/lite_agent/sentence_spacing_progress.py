"""Single-instruction stage guidance; no task IDs, answers, or tool routing."""
import re

from .completion_policy import effective_canonical_action
from .result_envelopes import iter_result_mappings

_INSTRUCTION = 'I am making a guideline for students of my course and would like to separate each sentence in the the first paragraph to improve readability. Please separate each sentence by creating one empty line space after each of them, as I am having hard time separating them one by one.'


def model_progress(state):
    # Deliberately exact scope: other Writer instructions receive no extra text.
    if state.domain != "libreoffice_writer" or state.instruction != _INSTRUCTION:
        return None
    splits = []
    for event in state.events:
        if not event.executed or event.error:
            continue
        domain, action, args = effective_canonical_action(event, state.domain)
        if domain == "libreoffice_writer" and action == "paragraph.split":
            for body in iter_result_mappings(event.result):
                if "parts" in body:
                    splits.append({key: body[key] for key in (
                        "parts", "following_paragraph", "split_at_paragraph_end",
                        "right_part_empty") if key in body})
                    break
    if not splits:
        return {"stage": "observe_then_separate", "guidance":
                "Read the complete first paragraph and its following paragraph before editing. "
                "Derive ALL internal sentence boundaries from that observed text before editing. "
                "When using paragraph.split, after_text can contain the list of all internal "
                "boundaries in one call; exclude the final sentence ending. Include observed "
                "inter-sentence whitespace on the left. Separate adjacent sentences "
                "with exactly one empty paragraph. Do not split at the final character: an end "
                "split creates an empty right part PLUS separator blanks, while the document "
                "may already contain a following blank. Preserve the original following content "
                "and spacing. Do not infer success from paragraph counts alone."}
    latest = splits[-1]
    parts = latest.get("parts", [])
    remaining = []
    single = []
    for part in parts:
        text = str(part.get("text", "")).strip()
        if not text:
            continue
        count = len(re.findall(r"[.!?]\s+(?=\S)", text))
        observed = {"index": part.get("index"), "text": part.get("text"),
                    "internal_sentence_boundaries": count}
        (remaining if count else single).append(observed)
    if not remaining:
        return {"stage": "verify_save_without_more_splitting",
                "observed_single_sentence_paragraphs": single,
                "latest_observed_split": latest,
                "guidance": "Every nonempty part in the latest split already contains a single "
                "sentence in its OWN paragraph. Splitting after that sentence's final punctuation "
                "does NOT separate it from its predecessor; it only adds surplus blank paragraphs. "
                "Do not split these already separated single-sentence paragraphs again. "
                "Read back the entire edited span and its following paragraph, verify one blank "
                "between sentences and preservation of following content, save if necessary, "
                "and propose_done when all original sentences are separated. If read-back actually "
                "shows a multi-sentence remainder, address only its internal boundaries."}
    return {"stage": "finish_remaining_sentences", "remaining_observed_parts": remaining,
            "latest_observed_split": latest,
            "guidance": "The request applies to EVERY sentence of the ORIGINAL first paragraph. "
            "A split creates a right part which may still contain MULTIPLE sentences. "
            "If the latest right part still contains multiple sentences, the task is UNFINISHED: "
            "continue separating that remainder using its current observed raw index. "
            "A successful split/save/verification checks that operation, not completion of all sentences. "
            "Do not switch to completion merely because some splits succeeded. "
            "Once ALL original sentences are separated, inspect the entire edited span AND the first following nonempty paragraph, "
            "including every intervening blank. Check one blank between adjacent sentences, "
            "no duplicate trailing blanks introduced by an end split, and unchanged later content. "
            "Reading only the first resulting sentence does not verify this request. "
            "If surplus empty parts were created, correct only those observed surplus parts. "
            "Save and perform a final structural read-back before proposing completion; "
            "do not repeat a successful split."}
