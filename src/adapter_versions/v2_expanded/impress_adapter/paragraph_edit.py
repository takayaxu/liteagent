"""Delete one model-selected native paragraph without replacing a text box."""
from __future__ import annotations

from typing import Any

from .errors import AdapterError


_STRUCT_FIELDS: dict[str, tuple[str, ...]] = {}


def _paragraphs(text: Any) -> list[Any]:
    enumeration = text.createEnumeration()
    result = []
    while enumeration.hasMoreElements():
        result.append(enumeration.nextElement())
    return result


def _value(value: Any) -> Any:
    """Compare native property values without proxy identities or repr addresses."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (tuple, list)):
        return tuple(_value(item) for item in value)
    if isinstance(value, bytes):
        return value.hex()
    if type(value).__module__ == "uno" and type(value).__name__ in {"Char", "ByteSequence"}:
        return (type(value).__name__, _value(value.value))
    if hasattr(value, "typeName"):
        if isinstance(value.value, str):  # UNO enum
            return (value.typeName, value.value)
        if value.typeName not in _STRUCT_FIELDS:
            import uno

            context = uno.getComponentContext()
            reflection = context.ServiceManager.createInstanceWithContext(
                "com.sun.star.reflection.CoreReflection", context)
            _STRUCT_FIELDS[value.typeName] = tuple(
                field.getName() for field in reflection.forName(value.typeName).getFields())
        return (value.typeName, tuple((key, _value(getattr(value, key)))
                                     for key in _STRUCT_FIELDS[value.typeName]))
    if hasattr(value, "getCount") and hasattr(value, "getByIndex"):
        return tuple(_value(value.getByIndex(i)) for i in range(value.getCount()))
    if hasattr(value, "getElementNames") and hasattr(value, "getByName"):
        return tuple((key, _value(value.getByName(key))) for key in sorted(value.getElementNames()))
    raise ValueError("unsupported native formatting value")


def _properties(obj: Any, prefixes: tuple[str, ...]) -> dict[str, Any]:
    properties = {}
    for prop in obj.getPropertySetInfo().getProperties():
        if prop.Name.startswith(prefixes) and not prop.Attributes & 16:  # READONLY
            value = obj.getPropertyValue(prop.Name)
            properties[prop.Name] = value.createClone() if hasattr(value, "createClone") else value
    return properties


def _signature(properties: dict[str, Any]) -> Any:
    return tuple((key, _value(value)) for key, value in sorted(properties.items()))


def _snapshot(paragraph: Any) -> dict[str, Any]:
    properties = _properties(paragraph, ("Para", "Numbering", "Outline", "WritingMode"))
    portions = paragraph.createEnumeration()
    runs = []
    run_properties = []
    has_fields = False
    while portions.hasMoreElements():
        portion = portions.nextElement()
        kind = str(portion.getPropertyValue("TextPortionType"))
        field_signature = None
        if kind == "TextField":
            field = portion.getPropertyValue("TextField")
            # A URL field elsewhere in the box must remain a field, with its
            # target and representation intact. Other fields are unsupported.
            if not field.supportsService("com.sun.star.text.TextField.URL"):
                raise ValueError("paragraph contains an unsupported text field")
            has_fields = True
            field_signature = _signature({p.Name: field.getPropertyValue(p.Name)
                                          for p in field.getPropertySetInfo().getProperties()})
        elif kind != "Text":
            raise ValueError("paragraph contains a non-text portion")
        text = str(portion.getString())
        if text:
            properties_for_run = _properties(portion, ("Char",))
            runs.append((text, (_signature(properties_for_run), field_signature)))
            run_properties.append((text, properties_for_run))
    return {"text": str(paragraph.getString()), "properties": properties,
            "format": _signature(properties), "runs": tuple(runs),
            "run_properties": run_properties, "has_fields": has_fields}


def _restore_runs(text: Any, paragraph: Any, saved: dict[str, Any]) -> None:
    if saved["has_fields"]:
        raise ValueError("cannot restore character ranges across URL fields")
    offset = 0
    for content, properties in saved["run_properties"]:
        cursor = text.createTextCursorByRange(paragraph.getStart())
        # UNO's character counts use UTF-16 code units and a signed short.
        for count, select in ((offset, False), (len(content.encode("utf-16-le")) // 2, True)):
            while count:
                step = min(count, 32767)
                if not cursor.goRight(step, select):
                    raise ValueError("character range could not be selected")
                count -= step
        if str(cursor.getString()) != content:
            raise ValueError("character range does not match the observed run")
        for name, value in properties.items():
            if _value(cursor.getPropertyValue(name)) != _value(value):
                cursor.setPropertyValue(name, value)
        offset += len(content.encode("utf-16-le")) // 2


def _preserve_paragraph(text: Any, paragraph: Any, saved: dict[str, Any]) -> None:
    observed = _snapshot(paragraph)
    if observed["format"] != saved["format"]:
        for name, value in saved["properties"].items():
            if _value(observed["properties"][name]) != _value(value):
                paragraph.setPropertyValue(name, value)
    if observed["runs"] != saved["runs"]:
        _restore_runs(text, paragraph, saved)
    observed = _snapshot(paragraph)
    if observed["format"] != saved["format"] or observed["runs"] != saved["runs"]:
        raise ValueError("remaining paragraph or character formatting changed")


def delete_paragraph(shape: Any, index: int, expected_text: str) -> dict[str, Any]:
    text = shape.getText()
    paragraphs = _paragraphs(text)
    if not 0 <= index < len(paragraphs):
        raise AdapterError("INVALID_REQUEST", "paragraph_index is out of range")
    if str(paragraphs[index].getString()) != expected_text:
        raise AdapterError("CONFLICT", "selected paragraph differs from expected_text; inspect again",
                           {"executed": False}, 409)
    if len(paragraphs) < 2:
        raise AdapterError("UNSUPPORTED_OPERATION", "cannot remove the only paragraph of a text shape")
    try:
        before = [_snapshot(paragraph) for paragraph in paragraphs]
        if before[index]["has_fields"]:
            raise ValueError("selected paragraph contains a URL field")
    except Exception as exc:
        raise AdapterError("UNSUPPORTED_OPERATION", "cannot verify reversible native paragraph deletion",
                           {"executed": False, "cause": str(exc)}, 422) from exc
    remaining = before[:index] + before[index + 1:]
    cursor = None
    removed = None
    failure = None
    try:
        # Ranges come from native paragraphs, not line arrays or Python character
        # offsets (which differ from UNO offsets for non-BMP Unicode text).
        if index + 1 < len(paragraphs):
            start, end = paragraphs[index].getStart(), paragraphs[index + 1].getStart()
        else:
            start, end = paragraphs[index - 1].getEnd(), paragraphs[index].getEnd()
        cursor = text.createTextCursorByRange(start)
        cursor.gotoRange(end, True)
        removed = str(cursor.getString())
        cursor.setString("")
        after = _paragraphs(text)
        if [str(p.getString()) for p in after] != [p["text"] for p in remaining]:
            raise ValueError("remaining paragraph text or count changed")
        for paragraph, saved in zip(after, remaining):
            # Removing a separator can inherit the deleted paragraph's paragraph
            # and character style. Restore only changed properties of survivors.
            _preserve_paragraph(text, paragraph, saved)
    except Exception as exc:
        failure = exc
    if failure is not None:
        restored = False
        recovery_error = None
        try:
            # Impress does not reliably record UNO text changes in its undo
            # manager. Reinsert only the removed range, then restore snapshots.
            if cursor is not None and removed is not None:
                cursor.setString(removed)
            recovered = _paragraphs(text)
            if [str(p.getString()) for p in recovered] != [p["text"] for p in before]:
                raise ValueError("original paragraphs could not be restored")
            for paragraph, saved in zip(recovered, before):
                _preserve_paragraph(text, paragraph, saved)
            actual = [_snapshot(p) for p in _paragraphs(text)]
            restored = [(p["text"], p["format"], p["runs"]) for p in actual] == [
                (p["text"], p["format"], p["runs"]) for p in before]
        except Exception as exc:
            recovery_error = str(exc)
        raise AdapterError("VERIFICATION_FAILED", "paragraph deletion could not preserve the remaining content",
                           {"restored": restored, "cause": str(failure),
                            "recovery_error": recovery_error}, 422) from failure
    return {"deleted_paragraph_index": index, "deleted_text": expected_text,
            "paragraph_count_before": len(before), "paragraph_count": len(remaining),
            "remaining_text_and_format_preserved": True,
            "guidance": "Paragraph indices shifted. Inspect before another edit; save the presentation and read back afterward."}
