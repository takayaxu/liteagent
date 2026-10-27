"""Observe explicit picture-only decks; leave all repair decisions to the model."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from .completion_policy import action_is_read_only, effective_canonical_action
from .instruction_semantics import requested_blank_slide_count


ACTIONS = ("presentation.inspect", "shape.delete", "shape.insert_image",
           "slide.create", "slide.delete", "slide.move", "presentation.save")


def picture_deck_spec(instruction: str) -> dict[str, Any] | None:
    """Conservative whole-deck scope, with no prescribed files or page count."""
    count = requested_blank_slide_count(instruction)
    if (not count or count > 100
            or not re.search(r"\bone\s+(?:image|picture)\s+per\s+slide\b", instruction, re.I)
            or not re.search(r"\b(?:in order|numerical order|numeric order)\b", instruction, re.I)
            or re.search(r"\b(?:not|never|don't|do not|additional|append|retain|keep|except)\b", instruction, re.I)
            or re.search(r"\b(?:add|insert|include|with)\s+(?:(?:a|an|the|some)\s+)?(?:titles?|subtitles?|text|textboxes?|captions?|logos?|shapes?|tables?)\b", instruction, re.I)
            or re.search(r"\b(?:add|insert)\s+\w+\s+blank\s+slides\b", instruction, re.I)):
        return None
    matches = list(re.finditer(
        r"\b([\w.-]*?)(\d+)\.(png|jpe?g)\s+(?:to|through|-)\s+"
        r"([\w.-]*?)(\d+)\.(png|jpe?g)\b", instruction, re.I))
    if len(matches) != 1:
        return None
    prefix, first, extension, last_prefix, last, last_extension = matches[0].groups()
    start, end = int(first), int(last)
    if prefix != last_prefix or extension != last_extension or end - start + 1 != count:
        return None
    padded = first.startswith("0") and len(first) > 1
    if padded and len(first) != len(last):
        return None
    names = [f"{prefix}{str(i).zfill(len(first)) if padded else i}.{extension}"
             for i in range(start, end + 1)]
    return {"count": count, "names": names}


def _fingerprint(value: Any) -> tuple | None:
    if not isinstance(value, dict) or value.get("status") != "known":
        return None
    digest = value.get("sha256")
    width, height = value.get("pixel_width"), value.get("pixel_height")
    if (value.get("algorithm") != "sha256-native-dib-v1"
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(width, int) or isinstance(width, bool) or width <= 0
            or not isinstance(height, int) or isinstance(height, bool) or height <= 0):
        return None
    return (value["algorithm"], digest, width, height)


def outcome_issues(state: Any, result_payload: Any, issue: Any) -> list[dict[str, Any]]:
    spec = picture_deck_spec(str(state.instruction))
    if not spec:
        return []
    pages: dict[int, tuple[dict, int]] = {}
    sources: dict[str, dict[str, tuple | None]] = {}
    current_url = None
    count = None
    last_step = None

    def source_observation(source: Any) -> None:
        if not isinstance(source, dict):
            return
        path = source.get("source_path")
        if not isinstance(path, str) or not path.startswith("/"):
            return
        name = PurePosixPath(path).name
        sources.setdefault(name, {})[path] = _fingerprint(source.get("graphic_fingerprint"))

    for event in state.events:
        kind = event.proposed.get("kind")
        if kind == "gui" and (event.executed or event.validated):
            pages.clear()
            sources.clear()
            count = None
            continue
        if kind != "adapter":
            continue
        domain, action, _ = effective_canonical_action(event, state.domain)
        if domain != "libreoffice_impress":
            if (event.executed or event.validated) and not action_is_read_only(action):
                pages.clear()
                sources.clear()
                count = None
            continue
        succeeded = event.executed and not getattr(event, "error", None)
        if action in {"presentation.open", "presentation.create_new", "presentation.close"} and succeeded:
            pages.clear()
            sources.clear()
            current_url = None
            count = None
        payload = result_payload(event) if succeeded else {}
        identity = payload.get("identity") or {}
        url = identity.get("url") or payload.get("url")
        if url and current_url and url != current_url and action != "presentation.save":
            pages.clear()
            sources.clear()
            count = None
        if url:
            current_url = url
        # A failed native write may already have modified the document. Saves
        # also invalidate old observations, including Save As document identity.
        if not action_is_read_only(action) and (succeeded or event.validated):
            pages.clear()
            count = None
        if not succeeded:
            continue
        if action == "shape.insert_image":
            source_observation(payload.get("source_image"))
        if action != "presentation.inspect":
            continue
        for source in payload.get("source_images", []):
            source_observation(source)
        if (payload.get("truncated") or payload.get("context_truncated")
                or payload.get("slides_omitted_from_context")):
            # Do not retain a previous complete read in preference to a newer
            # bounded read whose missing objects could hide a discrepancy.
            pages.clear()
            count = None
            continue
        observed_count = payload.get("slide_count")
        if not isinstance(observed_count, int) or isinstance(observed_count, bool):
            continue
        if count is not None and count != observed_count:
            pages.clear()
        count, last_step = observed_count, event.step
        entries = payload.get("slides")
        if not isinstance(entries, list):
            pages.clear()
            continue
        seen = set()
        for page in entries:
            if not isinstance(page, dict):
                continue
            index = page.get("index", page.get("slide", page.get("slide_index")))
            if not isinstance(index, int) or isinstance(index, bool) or index in seen:
                pages.clear()
                break
            seen.add(index)
            pages[index] = (page, event.step)

    def defect(code: str, target: Any, expected: Any, observed: Any,
               *, step: int | None = None, mismatch: bool = False) -> dict:
        return issue("image_deck." + code, target, expected, observed,
                     actions=ACTIONS, step=step, mismatch=mismatch)

    if count != spec["count"]:
        return [defect("slide_count", "presentation", spec["count"], count,
                       step=last_step, mismatch=count is not None)]
    issues = []
    for index, name in enumerate(spec["names"]):
        target = {"slide": index, "image": name}
        if index not in pages:
            issues.append(defect("page_unobserved", target, "complete inspection after final mutation and save", None))
            continue
        page, step = pages[index]
        raw = page.get("shapes")
        total = page.get("shape_count")
        if total is None and isinstance(raw, list):
            total = len(raw)
        if not isinstance(total, int) or isinstance(total, bool):
            issues.append(defect("objects_unobserved", target, "native total object count", None, step=step))
            continue
        if total != 1:
            issues.append(defect("extra_or_missing_objects", target,
                                 "exactly one picture and no other objects (including empty placeholders)",
                                 {"shape_count": total}, step=step, mismatch=True))
            continue
        if isinstance(raw, list) and len(raw) != total:
            issues.append(defect("objects_unobserved", target, "complete native object inventory",
                                 {"shape_count": total, "returned_objects": len(raw)}, step=step))
            continue
        graphics = ([s for s in raw if isinstance(s, dict)
                     and "graphicobjectshape" in str(s.get("kind", "")).casefold()]
                    if isinstance(raw, list) else page.get("graphic_shapes"))
        if page.get("graphic_shapes_omitted") or page.get("shapes_omitted") or not isinstance(graphics, list):
            issues.append(defect("picture_unobserved", target, "complete picture inventory", None, step=step))
            continue
        if len(graphics) != 1:
            issues.append(defect("picture_count", target, 1, len(graphics), step=step, mismatch=True))
            continue
        picture = graphics[0]
        if picture.get("visible") is not True or any(
                not isinstance(picture.get(k), (int, float)) or picture[k] <= 0 for k in ("width", "height")):
            issues.append(defect("picture_visibility", target, "visible picture with positive dimensions",
                                 {k: picture.get(k) for k in ("visible", "width", "height")}, step=step,
                                 mismatch=picture.get("visible") is False))
        actual = _fingerprint(picture.get("graphic_fingerprint"))
        candidates = sources.get(name, {})
        expected = next(iter(candidates.values())) if len(candidates) == 1 else None
        if actual is None or expected is None:
            issues.append(defect("content_unverified", target,
                                 "native image fingerprint matching the unambiguous source; inspect image_paths to observe source content",
                                 {"picture_fingerprint": actual, "source_paths": list(candidates)}, step=step))
        elif actual != expected:
            issues.append(defect("content_order_mismatch", target, expected, actual, step=step, mismatch=True))
    return issues
