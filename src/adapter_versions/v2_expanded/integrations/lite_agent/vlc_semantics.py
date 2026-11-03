from __future__ import annotations

import re


_PLAY_RE = re.compile(r"(?i)\b(?:open|play|start)\b")
_FUTURE_USE_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:so\s+(?:that\s+)?)?(?:I|we)\s+(?:can|could|may|might|will|would)\s+"
    r"(?:open|play|start)\b|"
    r"to\s+(?:open|play|start)\s+(?:(?:it|them)\s+)?"
    r"\b(?:later|whenever|anytime|tomorrow|eventually|in\s+the\s+future)\b)"
)
# Videos and Music are also ordinary media nouns. Require a location phrase
# before treating them as user directories; mentioning playback while describing
# a preference problem does not itself request opening a media file.
_LOCAL_LOCATION_RE = re.compile(
    r"(?i)\b(?:desktop|downloads?|home)\b|"
    r"\b(?:from|in|on|to|under)\s+(?:(?:my|the|our|your)\s+)?(?:videos|music)\b|"
    r"\b(?:videos|music)\s+(?:folder|directory)\b"
)
_MEDIA_RE = re.compile(r"(?i)\b(?:audio|clip|movie|music|song|track|video)\b")
_RECORDING_RE = re.compile(r"(?i)\brecord(?:ed|ing|ings)?\b")
_DIRECTORY_RE = re.compile(r"(?i)\b(?:directory|folder|path|location)\b")


def required_actions(domain: str, instruction: str) -> list[str]:
    """Return reusable VLC operation classes without extracting their arguments."""
    if domain != "vlc":
        return []
    actions: list[str] = []
    if _RECORDING_RE.search(instruction) and (
        _DIRECTORY_RE.search(instruction)
        or re.search(r"(?<![\w.-])/[\w .~/-]+", instruction)
    ):
        actions.append("preferences.configure")
    if (
        _PLAY_RE.search(_FUTURE_USE_RE.sub("", instruction))
        and _LOCAL_LOCATION_RE.search(instruction)
        and _MEDIA_RE.search(instruction)
    ):
        actions.append("playback.open")
    return actions
