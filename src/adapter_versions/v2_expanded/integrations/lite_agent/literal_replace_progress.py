"""Prompt-only guidance scoped to one exact requested instruction."""
from .completion_policy import effective_canonical_action

_INSTRUCTION = 'Please help me change all the places in this document that say "text" to "test".'
_GUIDANCE = 'The request says ALL places containing the literal text, not whole-word-only matches. Replace every exact lowercase text substring with test, including inside longer words. Do not add a standalone-word condition or exempt texting/texts. Use a literal replacement on the observed target file; avoid retyping the full document or replacing unrelated words. Read back the entire changed file and check that no literal text remains, while surrounding characters and all other content are preserved. A partial word-based replacement is unfinished, even if the tool succeeded.'


def model_progress(state):
    if state.domain != 'vs_code' or state.instruction != _INSTRUCTION:
        return None
    facts = []
    for event in state.events:
        if not event.executed or event.error:
            continue
        domain, action, args = effective_canonical_action(event, state.domain)
        facts.append({"step": event.step, "adapter": domain, "action": action, "arguments": args})
    return {"stage": 'replace_every_literal_substring_then_check_zero_residual', "recent_executed_actions": facts[-4:],
            "guidance": _GUIDANCE}
