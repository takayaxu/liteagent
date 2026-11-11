"""Prompt evidence for preserving directory layouts without replicating sources."""
import re

from .completion_policy import effective_canonical_action


def model_progress(state):
    instruction = state.instruction
    if not re.search(r'\bcopy\b', instruction, re.I) or not re.search(
        r'\bpreserv\w*\b.*\b(?:hierarchy|layout|structure)\b', instruction, re.I
    ):
        return None
    observed = []
    for event in state.events:
        if not event.executed or event.error:
            continue
        adapter, action, params = effective_canonical_action(event, state.domain)
        if adapter == 'os' and action in {
            'filesystem.find', 'filesystem.copy', 'filesystem.copy_to_directories'
        }:
            observed.append({'step': event.step, 'action': action, 'arguments': params})
    if not observed:
        return None
    return {'observed_operations': observed,
            'next_step': 'For each discovered source, determine its relative path under the source root '
            'and the matching destination path. Copy that source only to its own matching directory; '
            'do not supply directories belonging to other source files in destinations. '
            'copy_to_directories duplicates ONE source into EVERY supplied directory. '
            'After copying, compare the complete destination listing against the source relative-path '
            'set: check missing AND extra files, including earlier mistaken copies. '
            'If an earlier copy created extra files, inspect them and correct only those task-created '
            'extras before completion. Existing unrelated destination files must be preserved.'}
