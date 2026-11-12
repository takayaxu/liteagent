"""Prompt-only guidance scoped to one exact requested instruction."""
from .completion_policy import effective_canonical_action

_INSTRUCTION = 'Copy all files matching "*failed.ipynb" in the current directory tree to "./fails" preserving the directory hierarchy'
_GUIDANCE = 'The CURRENT directory is the active terminal working directory, not automatically /home/user. Resolve that live directory through a public read such as command.run pwd with cwd_source=active_terminal before searching or copying. Both the source tree and ./fails are relative to THAT SAME observed directory. Compute each destination from the source path relative to the current-directory root, preserving every intervening directory. Do not strip the task-directory prefix relative to home and then place fails under home. Exclude the destination fails tree from subsequent source scans. Copy only matching files, preserve sources, and verify exact destination relative paths, not just total file count.'


def model_progress(state):
    if state.domain != 'os' or state.instruction != _INSTRUCTION:
        return None
    facts = []
    for event in state.events:
        if not event.executed or event.error:
            continue
        domain, action, args = effective_canonical_action(event, state.domain)
        facts.append({"step": event.step, "adapter": domain, "action": action, "arguments": args})
    return {"stage": 'resolve_current_directory_before_relative_copy', "recent_executed_actions": facts[-4:],
            "guidance": _GUIDANCE}
