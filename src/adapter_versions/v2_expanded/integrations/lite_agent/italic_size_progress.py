"""Single-request progress facts for italic font resizing."""
from .completion_policy import effective_canonical_action
from .result_envelopes import iter_result_mappings

_INSTRUCTION = 'I found Italic font very hard to discern from the normal text for me, as it is also dark black with the same size. Current font size is 12 and I want to change the font size of italicized words to 14 to make it more discernible. Can you help me on this?'


def _bodies(result):
    yield from iter_result_mappings(result)
    if isinstance(result, dict) and isinstance(result.get("context_hint"), dict):
        yield result["context_hint"]


def model_progress(state):
    if state.domain != "libreoffice_writer" or state.instruction != _INSTRUCTION:
        return None
    matches = {}
    changed = set()
    last_find = None
    last_write_step = 0
    for event in state.events:
        if not event.executed or event.error:
            continue
        domain, action, args = effective_canonical_action(event, state.domain)
        if domain != "libreoffice_writer":
            continue
        if action == "text.find" and args.get("format", {}).get("italic") is True:
            for body in _bodies(event.result):
                if isinstance(body.get("matches"), list):
                    last_find = {"step": event.step, "has_more": body.get("has_more"),
                                 "returned_count": len(body["matches"])}
                    for m in body["matches"]:
                        key = (m.get("paragraph_index"), m.get("start_offset"), m.get("end_offset"))
                        matches[key] = m
                    break
        if action == "text.set_format" and args.get("font_size") == 14:
            changed.add((args.get("paragraph_index"), args.get("start_offset"), args.get("end_offset")))
            last_write_step = event.step
    remaining = [m for k, m in matches.items()
                 if m.get("format", {}).get("font_size") != 14 and k not in changed]
    base = {"observed_match_count": len(matches), "successful_exact_range_updates": len(changed),
            "remaining_observed_matches": remaining, "last_italic_search": last_find}
    if not matches:
        return {**base, "stage": "find_all_italic_runs", "guidance":
                "Read all italic matches with formatting and complete any has_more continuation. "
                "Use paragraph_index/start_offset/end_offset from each observed match. "
                "Those offsets are paragraph-relative; they are NOT offsets inside matched_text. "
                "Change only font_size, preserving italics, superscript, bold, and other properties."}
    if remaining:
        return {**base, "stage": "resize_every_remaining_range", "guidance":
                "The remaining_observed_matches list contains ranges not yet confirmed at size14. "
                "Choose one exact observed range and change only its font_size to14. "
                "Repeated words at different offsets are DISTINCT targets; do not skip them. "
                "A successful edit proves only that one range, not all italic text. "
                "Use paragraph-relative offsets with text.set_format and expected_text from that "
                "match. Continue until every remaining observed match is handled."}
    return {**base, "stage": "requery_all_italic_sizes_then_save", "guidance":
            "Every observed range has a successful size update. Re-run the format-filtered "
            "text.find for italic=true across the entire document and inspect font_size for "
            "ALL matches, including repeated letters and superscripts. If any size differs "
            "from14, handle that exact range. A generic document.inspect cannot verify all "
            "italic runs. Only complete after a full untruncated search confirms all at14 "
            "and the final changes are saved/read back."}
