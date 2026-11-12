"""Exact-instruction bibliography prompts derived only from public observations."""
from .completion_policy import effective_canonical_action
from .result_envelopes import iter_result_mappings

_INSTRUCTION = 'Help me adding "Steinberg, F. M., Bearden, M. M., & Keen, C. L. (2003). Cocoa and chocolate flavonoids: Implications for cardiovascular health. Journal of the American Dietetic Association, 103(2), 215-223. doi: 10.1053/jada.2003.50028" to my reference list, and add a cross reference (using reference number) in the fourth paragraph where I marked "<add here>".'


def model_progress(state):
    if state.domain != "libreoffice_writer" or state.instruction != _INSTRUCTION:
        return None
    numbered = {}
    writes = []
    observed_new_reference = None
    citation = state.instruction.split('"', 2)[1]
    for event in state.events:
        if not event.executed or event.error:
            continue
        domain, action, args = effective_canonical_action(event, state.domain)
        if domain != "libreoffice_writer":
            continue
        if action == "document.inspect":
            bodies = list(iter_result_mappings(event.result))
            hint = event.result.get("context_hint") if isinstance(event.result, dict) else None
            if isinstance(hint, dict):
                bodies.append(hint)
            for body in bodies:
                for p in body.get("paragraph_details", []):
                    if p.get("text") == citation:
                        observed_new_reference = {k: p.get(k) for k in ("index", "text", "numbering")}
                    if p.get("numbering", {}).get("is_numbered"):
                        numbered[p["index"]] = {k: p.get(k) for k in ("index", "text", "numbering")}
        if action in {"document.append_paragraphs", "paragraph.replace_text",
                      "paragraph.apply_numbering", "bookmark.create", "cross_reference.insert"}:
            writes.append({"step": event.step, "action": action, "arguments": args})
    base = {"observed_numbered_paragraphs": list(numbered.values()),
            "observed_new_reference": observed_new_reference,
            "executed_bibliography_edits": writes,
            "meaning": "Observed facts only; success of an individual edit does not validate the reference list."}
    if not writes:
        return {**base, "stage": "read_complete_reference_tail", "guidance":
                "Inspect the reference list through its LAST existing entry before adding the "
                "user-supplied citation. Preserve its list ordering and native numbering. "
                "If empty paragraphs separate the last reference from document end, place the "
                "citation directly after the reference list using an observed empty paragraph "
                "there, rather than appending beyond unrelated trailing blanks. "
                "Do not guess a number from an earlier inspection window."}
    if observed_new_reference is None:
        return {**base, "stage": "locate_the_actual_inserted_citation", "guidance":
                "The citation text was submitted, but its actual paragraph index has NOT been "
                "read back. Read the appended tail or find the exact citation text NOW before "
                "numbering or bookmarking. document.append_paragraphs appends at document END, "
                "which can be beyond multiple empty paragraphs. Never assume last reference "
                "index +1 is the appended citation. A numbering operation can succeed on an "
                "empty paragraph and still target the WRONG source. Only use the paragraph "
                "whose read-back text matches the user-supplied citation."}
    if not any(w["action"] == "cross_reference.insert" for w in writes):
        return {**base, "stage": "continue_native_numbering_then_reference", "guidance":
                "The new reference must CONTINUE the existing bibliography list. Read the LAST "
                "existing numbered reference and the new citation. When applying its native "
                "numbering, copy that terminal reference's numbering with restart=false; do not "
                "restart at a guessed number or reuse an existing label. Bookmark the new "
                "numbered source, then replace only the observed <add here> marker with a native "
                "number cross-reference. Do not type a reference number as ordinary text."}
    return {**base, "stage": "verify_both_reference_source_and_destination", "guidance":
            "Read back BOTH the new bibliography entry with its actual list label AND the "
            "cross-reference at the marked destination. Confirm the label continues after the "
            "last old entry, has no duplicate number, and matches the field presentation. "
            "A successful field insertion or a read of only the destination does not prove "
            "correct numbering. Preserve old references and surrounding text; save and read "
            "back after the last edit before propose_done."}
