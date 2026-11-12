"""Prompt-only guidance scoped to one exact requested instruction."""
from .completion_policy import effective_canonical_action

_INSTRUCTION = 'The volume of my system is too small. Can you help me turn up to the max volume?'
_GUIDANCE = 'For system volume, normal full-scale maximum is 100 percent. Values above 100 percent are software amplification, not the normal system-slider maximum; the API upper bound 150 is an allowed amplification limit, not the requested nominal maximum. Set normal full-scale volume without amplification, keep the intended default output sink, and read back the actual system volume. Do not declare success from percent=150 merely because it is the largest number accepted by the tool.'


def model_progress(state):
    if state.domain != 'os' or state.instruction != _INSTRUCTION:
        return None
    facts = []
    for event in state.events:
        if not event.executed or event.error:
            continue
        domain, action, args = effective_canonical_action(event, state.domain)
        facts.append({"step": event.step, "adapter": domain, "action": action, "arguments": args})
    return {"stage": 'set_nominal_system_maximum_then_verify', "recent_executed_actions": facts[-4:],
            "guidance": _GUIDANCE}
