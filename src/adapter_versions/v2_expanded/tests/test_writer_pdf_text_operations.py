from collections import Counter
from pathlib import Path
import zipfile

import pytest

from writer_adapter.errors import AdapterError
from writer_adapter.pdf_export import (
    PdfLineEnd, _insert_pdf_space, _patch_pdf_lines,
    preserve_docx_soft_wrap_spaces,
)


fitz = pytest.importorskip("fitz")


def _pdf(tmp_path, stream, *, widths=True):
    document = fitz.open()
    page = document.new_page(width=600, height=400)
    cmap = document.get_new_xref()
    document.update_object(cmap, "<<>>")
    entries = "\n".join(f"<{i:02X}><{i:04X}>" for i in range(32, 127))
    document.update_stream(cmap, (
        "1 begincodespacerange\n<00><FF>\nendcodespacerange\n"
        f"96 beginbfchar\n{entries}\n<7F><006600660069>\nendbfchar"
    ).encode())
    font = document.get_new_xref()
    metrics = " ".join(str(round(fitz.get_text_length(
        chr(i), fontname="helv", fontsize=1000,
    ))) for i in range(32, 127))
    metric_object = f"/FirstChar 32 /LastChar 126 /Widths [{metrics}]" if widths else ""
    document.update_object(font, (
        f"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica {metric_object} "
        f"/ToUnicode {cmap} 0 R >>"
    ))
    document.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font} 0 R >> >>")
    content = document.get_new_xref()
    document.update_object(content, "<<>>")
    document.update_stream(content, stream)
    page.set_contents(content)
    path = tmp_path / "input.pdf"
    document.save(path)
    document.close()
    return path, font


def _docx(tmp_path, paragraph):
    path = tmp_path / "source.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p></w:body></w:document>"
        ))
    return path


def _split_line_stream():
    # A distant native space is grouped with the following text object by the
    # layout extractor. The first target ends inside its native text show.
    return (
        b"BT 50 200 Td /F1 11 Tf[<5469746C652E>-1000<20>]TJ ET\n"
        b"BT 88.645 200 Td /F1 11 Tf<4E657874>Tj ET\n"
        b"BT 50 180 Td /F1 11 Tf<636F6E74696E756174696F6E>Tj ET"
    )


def _glyphs(document):
    return [(char[0], tuple(round(n, 3) for n in char[2]))
            for trace in document[0].get_texttrace() for char in trace["chars"]]


def test_native_space_assigned_to_next_line_keeps_original_glyphs_and_line_breaks(tmp_path):
    path, _ = _pdf(tmp_path, _split_line_stream())
    source = _docx(tmp_path, "Title. Next continuation")
    source_bytes = source.read_bytes()
    with fitz.open(path) as before:
        assert before[0].get_text().splitlines() == ["Title.", " Next", "continuation"]
        glyphs = Counter(_glyphs(before))
    result = preserve_docx_soft_wrap_spaces(source, path)
    assert result["target_count"] == result["patched_trailing_spaces"] == 2
    with fitz.open(path) as after:
        assert after[0].get_text().splitlines() == ["Title. ", " Next ", "continuation"]
        added = Counter(_glyphs(after)) - glyphs
        assert not glyphs - Counter(_glyphs(after))
        assert sum(added.values()) == 2
        assert {char for char, _ in added} == {32}
    assert source.read_bytes() == source_bytes


@pytest.mark.parametrize("terminal_matrix", [False, True])
def test_merged_layout_span_uses_last_native_text_object(tmp_path, terminal_matrix):
    operator = b"1 0 0.267949 1 76 200 Tm" if terminal_matrix else b"76 200 Td"
    path, _ = _pdf(tmp_path, (
        b"BT 1 0 0.267949 1 50 200 Tm /F1 11 Tf<416C70686120>Tj ET\n"
        b"BT " + operator + b" /F1 11 Tf<62657461>Tj ET\n"
        b"BT 50 180 Td /F1 11 Tf<67616D6D61>Tj ET"
    ))
    source = _docx(tmp_path, "Alpha beta gamma")
    result = preserve_docx_soft_wrap_spaces(source, path)
    assert result["target_count"] == result["patched_trailing_spaces"] == 1
    with fitz.open(path) as document:
        assert document[0].get_text().splitlines() == ["Alpha beta ", "gamma"]


@pytest.mark.parametrize("problem", ["state", "widths"])
def test_unsupported_middle_insertion_keeps_original_pdf(tmp_path, problem):
    stream = (b"0 Tc\n" if problem == "state" else b"") + _split_line_stream()
    path, _ = _pdf(tmp_path, stream, widths=problem != "widths")
    source = _docx(tmp_path, "Title. Next continuation")
    original = path.read_bytes()
    with pytest.raises(AdapterError, match="text state|space advance"):
        preserve_docx_soft_wrap_spaces(source, path)
    assert path.read_bytes() == original


def test_same_position_in_different_contents_is_ambiguous(tmp_path):
    path, _ = _pdf(tmp_path, b"BT 50 200 Td /F1 11 Tf<416C706861>Tj ET")
    with fitz.open(path) as document:
        page = document[0]
        original = page.get_contents()[0]
        duplicate = document.get_new_xref()
        document.update_object(duplicate, "<<>>")
        document.update_stream(duplicate, document.xref_stream(original))
        document.xref_set_key(page.xref, "Contents", f"[{original} 0 R {duplicate} 0 R]")
        target = PdfLineEnd(50, 200, "Helvetica", "Alpha", 5)
        with pytest.raises(AdapterError, match="uniquely match"):
            _patch_pdf_lines(document, {0: [target]})


def test_same_resource_name_in_form_and_page_is_not_silently_overwritten(tmp_path):
    parent = tmp_path / "parent"
    form = tmp_path / "form"
    parent.mkdir()
    form.mkdir()
    stream = b"BT 50 200 Td /F1 11 Tf<416C706861>Tj ET"
    path, _ = _pdf(parent, stream)
    form_path, _ = _pdf(form, stream)
    with fitz.open(path) as document, fitz.open(form_path) as source:
        document[0].show_pdf_page(fitz.Rect(300, 200, 600, 400), source, 0)
        fonts = document[0].get_fonts(full=True)
        assert len({font[0] for font in fonts if font[4] == "F1"}) == 2
        with pytest.raises(AdapterError, match="ambiguous PDF font resource"):
            _patch_pdf_lines(document, {0: [PdfLineEnd(50, 200, "Helvetica", "Alpha", 5)]})


@pytest.mark.parametrize("body,trace,offset", [
    (b"<7F>Tj", "ffi", 1),  # A ligature cannot be split into partial code points.
    (b"<01>Tj", "x", 1),   # Unknown code points must not be guessed.
    (b"<416C706861>Tj", "other", 5),
])
def test_unknown_codes_ligature_boundaries_and_trace_mismatch_fail(tmp_path, body, trace, offset):
    path, font = _pdf(tmp_path, b"BT 50 200 Td /F1 11 Tf<416C706861>Tj ET")
    with fitz.open(path) as document, pytest.raises(AdapterError):
        _insert_pdf_space(document, font, body, PdfLineEnd(50, 200, "Helvetica", trace, offset),
                          default_text_state=True)


def test_failed_saved_readback_does_not_replace_original(tmp_path, monkeypatch):
    from writer_adapter import pdf_export
    path, _ = _pdf(tmp_path, b"BT 50 200 Td /F1 11 Tf<416C706861>Tj ET\n"
                             b"BT 50 180 Td /F1 11 Tf<62657461>Tj ET")
    source = _docx(tmp_path, "Alpha beta")
    original = path.read_bytes()
    monkeypatch.setattr(pdf_export, "_append_pdf_space_code", lambda body, code: body)
    with pytest.raises(AdapterError, match="saved PDF"):
        preserve_docx_soft_wrap_spaces(source, path)
    assert path.read_bytes() == original
    assert not list(Path(tmp_path).glob(".*.tmp"))
