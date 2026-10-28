from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import time
from typing import Any, Iterable
import xml.etree.ElementTree as ET
import zipfile

from .errors import AdapterError


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

WORD_P = f"{{{WORD_NS}}}p"
WORD_TEXT_NODES = frozenset(
    {
        f"{{{WORD_NS}}}t",
        f"{{{WORD_NS}}}instrText",
    }
)
WORD_SPACING_NODES = frozenset(
    {
        f"{{{WORD_NS}}}tab",
        f"{{{WORD_NS}}}br",
        f"{{{WORD_NS}}}cr",
    }
)

PDF_NUMBER = rb"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
PDF_TEXT_BLOCK_RE = re.compile(
    rb"BT\s+(?P<position>(?:" + PDF_NUMBER + rb"\s+){1,5}" + PDF_NUMBER
    + rb")\s+(?P<operator>Td|Tm)\s+/(?P<font>[A-Za-z0-9_.-]+)\s+"
    + PDF_NUMBER + rb"\s+Tf(?P<body>.*?)\s+ET",
    re.DOTALL,
)
PDF_HEX_RE = re.compile(rb"<([0-9A-Fa-f]*)>")


@dataclass(frozen=True)
class PdfLineEnd:
    x: float
    y: float
    font: str
    trace_text: str
    text_offset: int


@dataclass(frozen=True)
class DocxTextSources:
    body: tuple[str, ...]
    headers: dict[str, tuple[str, ...]]
    footers: dict[str, tuple[str, ...]]
    even_and_odd: bool
    title_page: bool


def _collapse_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _leaf_paragraph_texts(root: ET.Element) -> tuple[str, ...]:
    paragraphs = []
    for paragraph in root.iter(WORD_P):
        if sum(1 for _item in paragraph.iter(WORD_P)) > 1:
            continue
        chunks = []
        for node in paragraph.iter():
            if node.tag in WORD_TEXT_NODES and node.text:
                chunks.append(node.text)
            elif node.tag in WORD_SPACING_NODES:
                chunks.append(" ")
        text = _collapse_text("".join(chunks))
        if text:
            paragraphs.append(text)
    return tuple(paragraphs)


def _part_path(target: str) -> str | None:
    path = PurePosixPath(target.lstrip("/"))
    if not target.startswith("/"):
        path = PurePosixPath("word") / path
    normalized = PurePosixPath(os.path.normpath(str(path)))
    if (
        not normalized.parts
        or normalized.parts[0] != "word"
        or ".." in normalized.parts
    ):
        return None
    return str(normalized)


def _unique_part_texts(
    archive: zipfile.ZipFile,
    targets: dict[str, set[str]],
) -> dict[str, tuple[str, ...]]:
    result = {}
    names = set(archive.namelist())
    for kind, candidates in targets.items():
        if len(candidates) != 1:
            continue
        path = _part_path(next(iter(candidates)))
        if path is None or path not in names:
            continue
        result[kind] = _leaf_paragraph_texts(ET.fromstring(archive.read(path)))
    return result


def load_docx_text_sources(path: Path | None) -> DocxTextSources | None:
    if path is None or path.suffix.lower() != ".docx" or not path.is_file():
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                return None
            document = ET.fromstring(archive.read("word/document.xml"))
            relationships = {}
            relationship_path = "word/_rels/document.xml.rels"
            if relationship_path in names:
                relationship_root = ET.fromstring(archive.read(relationship_path))
                relationships = {
                    item.attrib["Id"]: item.attrib["Target"]
                    for item in relationship_root.iter(
                        f"{{{PACKAGE_REL_NS}}}Relationship"
                    )
                    if "Id" in item.attrib and "Target" in item.attrib
                }

            related: dict[str, dict[str, set[str]]] = {
                "header": defaultdict(set),
                "footer": defaultdict(set),
            }
            title_page = False
            for section in document.iter(f"{{{WORD_NS}}}sectPr"):
                title_page = title_page or any(
                    item.tag == f"{{{WORD_NS}}}titlePg" for item in section
                )
                for role in ("header", "footer"):
                    for reference in section.iter(f"{{{WORD_NS}}}{role}Reference"):
                        kind = reference.attrib.get(f"{{{WORD_NS}}}type", "default")
                        relation_id = reference.attrib.get(f"{{{OFFICE_REL_NS}}}id")
                        target = relationships.get(str(relation_id))
                        if target:
                            related[role][kind].add(target)

            even_and_odd = False
            if "word/settings.xml" in names:
                settings = ET.fromstring(archive.read("word/settings.xml"))
                even_and_odd = any(
                    item.tag == f"{{{WORD_NS}}}evenAndOddHeaders"
                    for item in settings.iter()
                )
            return DocxTextSources(
                body=_leaf_paragraph_texts(document),
                headers=_unique_part_texts(archive, related["header"]),
                footers=_unique_part_texts(archive, related["footer"]),
                even_and_odd=even_and_odd,
                title_page=title_page,
            )
    except (ET.ParseError, KeyError, OSError, zipfile.BadZipFile):
        return None


def _page_part_kind(sources: DocxTextSources, page_index: int) -> str:
    if page_index == 0 and sources.title_page:
        return "first"
    if sources.even_and_odd and (page_index + 1) % 2 == 0:
        return "even"
    return "default"


def _page_text_corpus(
    sources: DocxTextSources,
    page_index: int,
) -> tuple[str, ...]:
    kind = _page_part_kind(sources, page_index)
    header = sources.headers.get(kind) or sources.headers.get("default", ())
    footer = sources.footers.get(kind) or sources.footers.get("default", ())
    return (*sources.body, *header, *footer)


def _soft_wrap_line_targets(
    lines: Iterable[str],
    paragraphs: Iterable[str],
) -> Counter[str]:
    line_list = list(lines)
    paragraph_list = tuple(paragraphs)
    targets: Counter[str] = Counter()
    for current, following in zip(line_list, line_list[1:]):
        if not current or not following or current.endswith((" ", "\u00a0")):
            continue
        joined = _collapse_text(f"{current} {following}")
        if joined and any(joined in paragraph for paragraph in paragraph_list):
            targets[current] += 1
    return targets


def _derive_soft_wrap_targets(
    document: Any,
    sources: DocxTextSources,
) -> Counter[tuple[int, str]]:
    targets: Counter[tuple[int, str]] = Counter()
    for page_index, page in enumerate(document):
        for text, count in _soft_wrap_line_targets(
            page.get_text().splitlines(),
            _page_text_corpus(sources, page_index),
        ).items():
            targets[(page_index, text)] += count
    return targets


def _append_pdf_space_code(body: bytes, code: bytes) -> bytes:
    if re.search(rb"\]\s*TJ\s*$", body):
        return re.sub(rb"\]\s*TJ\s*$", b"<" + code + b">]TJ", body)
    if re.search(rb">\s*Tj\s*$", body):
        return re.sub(rb">\s*Tj\s*$", code + b">Tj", body)
    raise AdapterError(
        "PDF_NORMALIZATION_FAILED",
        "unsupported PDF text-show operator while preserving a soft-wrap space",
    )


def _pdf_space_code(document: Any, font_xref: int) -> bytes:
    font_object = document.xref_object(font_xref)
    match = re.search(r"/ToUnicode\s+(\d+)\s+0\s+R", font_object)
    if not match:
        raise AdapterError(
            "PDF_NORMALIZATION_FAILED",
            "PDF font has no ToUnicode map for preserving soft-wrap spaces",
        )
    cmap = document.xref_stream(int(match.group(1)))
    match = re.search(rb"<([0-9A-Fa-f]+)>\s*<0020>", cmap)
    if not match:
        raise AdapterError(
            "PDF_NORMALIZATION_FAILED",
            "PDF font has no encoded space glyph",
        )
    return match.group(1).upper()


def _pending_pdf_lines(
    document: Any,
    targets: Counter[tuple[int, str]],
) -> dict[int, list[PdfLineEnd]]:
    remaining = targets.copy()
    pending: dict[int, list[PdfLineEnd]] = defaultdict(list)
    for page_index, page in enumerate(document):
        traces = page.get_texttrace()
        for block in page.get_text("rawdict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(
                    char["c"] for span in line["spans"] for char in span["chars"]
                )
                key = (page_index, text)
                if remaining[key] <= 0:
                    continue
                span = line["spans"][-1]
                char = span["chars"][-1]
                # Layout spans can merge several text objects, and synthetic
                # spaces can have an origin belonging to the preceding object.
                # Locate the actual final character rather than the span start.
                candidates = [
                    (trace, offset)
                    for trace in traces if trace["font"] == span["font"]
                    for offset, traced in enumerate(trace["chars"], 1)
                    if chr(traced[0]) == char["c"]
                    and all(abs(a - b) < 0.25 for a, b in zip(
                        traced[2], char["origin"]
                    ))
                ]
                if len(candidates) != 1:
                    raise AdapterError(
                        "PDF_NORMALIZATION_FAILED",
                        "could not uniquely locate a soft-wrap character in PDF text traces",
                        {"page": page_index, "candidate_count": len(candidates)},
                    )
                trace, offset = candidates[0]
                pending[page_index].append(
                    PdfLineEnd(
                        float(trace["chars"][0][2][0]),
                        float(page.rect.height - trace["chars"][0][2][1]),
                        trace["font"],
                        "".join(chr(item[0]) for item in trace["chars"]),
                        offset,
                    )
                )
                remaining[key] -= 1
    if sum(remaining.values()):
        raise AdapterError(
            "PDF_NORMALIZATION_FAILED",
            "could not locate every derived soft-wrap line in the PDF layout",
            {"missing_count": sum(remaining.values())},
        )
    return dict(pending)


def _pdf_text_boundaries(
    document: Any, font_xref: int, body: bytes,
) -> tuple[str, dict[int, int]]:
    """Decode a supported single show and retain complete glyph boundaries."""
    font_object = document.xref_object(font_xref)
    reference = re.search(r"/ToUnicode\s+(\d+)\s+0\s+R", font_object)
    cmap = document.xref_stream(int(reference[1])) if reference else b""
    mapping = {
        code.upper(): bytes.fromhex(value.decode("ascii")).decode("utf-16-be")
        for section in re.findall(rb"beginbfchar(.*?)endbfchar", cmap, re.DOTALL)
        for code, value in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", section)
    }
    widths = {len(code) for code in mapping}
    show = re.fullmatch(
        rb"\s*(?:\[(?:\s*(?:<[0-9A-Fa-f]*>|" + PDF_NUMBER
        + rb"))*\s*\]\s*TJ|<[0-9A-Fa-f]*>\s*Tj)\s*", body,
    )
    if not mapping or len(widths) != 1 or b"beginbfrange" in cmap or show is None:
        raise AdapterError(
            "PDF_NORMALIZATION_FAILED",
            "unsupported PDF font encoding or text-show block for a soft-wrap line",
        )
    width = next(iter(widths))
    text = ""
    boundaries = {}
    for string in PDF_HEX_RE.finditer(body):
        encoded = string[1].upper()
        if len(encoded) % width:
            raise AdapterError("PDF_NORMALIZATION_FAILED", "incomplete PDF character code")
        for start in range(0, len(encoded), width):
            code = encoded[start:start + width]
            if code not in mapping:
                raise AdapterError("PDF_NORMALIZATION_FAILED", "unknown PDF character code")
            text += mapping[code]
            boundaries[len(text)] = string.start(1) + start + width
    return text, boundaries


def _pdf_space_advance(document: Any, font_xref: int, code: bytes) -> float:
    """Return the native simple-font width in TJ's thousandth-em units."""
    subtype = document.xref_get_key(font_xref, "Subtype")[1]
    first_type, first = document.xref_get_key(font_xref, "FirstChar")
    width_type, widths = document.xref_get_key(font_xref, "Widths")
    if width_type == "xref":
        widths = document.xref_object(int(widths.split()[0]))
        width_type = "array"
    if (subtype not in {"/TrueType", "/Type1"} or first_type != "int"
            or width_type != "array" or len(code) != 2):
        raise AdapterError("PDF_NORMALIZATION_FAILED", "unsupported PDF space advance")
    if re.fullmatch(rb"\[\s*(?:" + PDF_NUMBER + rb"\s*)*\]", widths.encode()) is None:
        raise AdapterError("PDF_NORMALIZATION_FAILED", "unsupported PDF font widths")
    values = re.findall(PDF_NUMBER, widths.encode())
    index = int(code, 16) - int(first)
    if not 0 <= index < len(values) or float(values[index]) <= 0:
        raise AdapterError("PDF_NORMALIZATION_FAILED", "missing PDF space width")
    return float(values[index])


def _insert_pdf_space(
    document: Any, font_xref: int, body: bytes, target: PdfLineEnd,
    *, default_text_state: bool,
) -> bytes:
    text, boundaries = _pdf_text_boundaries(document, font_xref, body)
    if text != target.trace_text or target.text_offset not in boundaries:
        raise AdapterError(
            "PDF_NORMALIZATION_FAILED",
            "PDF text operation differs from its trace or ends inside a ligature",
        )
    code = _pdf_space_code(document, font_xref)
    if target.text_offset == len(text):
        return _append_pdf_space_code(body, code)
    if not default_text_state:
        raise AdapterError(
            "PDF_NORMALIZATION_FAILED",
            "cannot preserve subsequent PDF glyph positions with non-default text state",
        )
    advance = _pdf_space_advance(document, font_xref, code)
    offset = boundaries[target.text_offset]
    # Back up before writing the space, so it does not extend the line's right
    # edge and merge separate layout lines. Its advance restores the original
    # position before the original suffix and TJ adjustments resume.
    patched = body[:offset] + b">" + f"{advance:g}".encode() + b"<" + code + body[offset:]
    if re.search(rb"\]\s*TJ\s*$", body):
        return patched
    return b"[" + re.sub(rb"Tj\s*$", b"]TJ", patched.strip())


def _patch_pdf_lines(
    document: Any,
    pending: dict[int, list[PdfLineEnd]],
) -> int:
    patched = 0
    for page_index, wanted in pending.items():
        page = document[page_index]
        fonts: dict[str, dict[int, Any]] = defaultdict(dict)
        for font in page.get_fonts(full=True):
            fonts[font[4]][int(font[0])] = font
        streams = {xref: document.xref_stream(xref) for xref in page.get_contents()}
        # Without interpreting inherited text/graphics states, middle-of-show
        # insertion is safe only when the page never changes those defaults.
        default_state = not any(
            re.search(rb"\b(?:Tc|Tw|Tz|Ts|cm|gs)\b", stream)
            for stream in streams.values()
        )
        candidates: dict[int, list[tuple[int, Any, int]]] = defaultdict(list)
        for content_xref, stream in streams.items():
            for match in PDF_TEXT_BLOCK_RE.finditer(stream):
                position = [float(value) for value in match["position"].split()]
                if len(position) != (2 if match["operator"] == b"Td" else 6):
                    continue
                x, y = position[-2:]
                resources = fonts.get(match["font"].decode("ascii"), {})
                if not resources:
                    continue
                for index, item in enumerate(wanted):
                    if abs(item.x - x) >= 0.25 or abs(item.y - y) >= 0.25:
                        continue
                    if len(resources) != 1:
                        raise AdapterError(
                            "PDF_NORMALIZATION_FAILED",
                            "ambiguous PDF font resource across content scopes",
                        )
                    font = next(iter(resources.values()))
                    if item.font == font[3].split("+", 1)[-1]:
                        candidates[index].append((content_xref, match, int(font[0])))
        if any(len(candidates[index]) != 1 for index in range(len(wanted))):
            raise AdapterError(
                "PDF_NORMALIZATION_FAILED",
                "could not uniquely match every derived soft-wrap line to a PDF text operation",
                {"page": page_index},
            )
        replacements_by_stream: dict[int, list[tuple[int, int, bytes]]] = defaultdict(list)
        used = set()
        for index, item in enumerate(wanted):
            content_xref, match, font_xref = candidates[index][0]
            identity = (content_xref, match.start())
            if identity in used:
                raise AdapterError("PDF_NORMALIZATION_FAILED", "multiple lines share one PDF text operation")
            used.add(identity)
            replacement = _insert_pdf_space(
                document, font_xref, match["body"], item, default_text_state=default_state,
            )
            replacements_by_stream[content_xref].append(
                (match.start("body"), match.end("body"), replacement)
            )
        for content_xref, replacements in replacements_by_stream.items():
            stream = streams[content_xref]
            for start, end, replacement in sorted(replacements, reverse=True):
                stream = stream[:start] + replacement + stream[end:]
                patched += 1
            document.update_stream(content_xref, stream)
    return patched


def preserve_docx_soft_wrap_spaces(
    source_path: Path | None,
    pdf_path: Path,
) -> dict[str, Any]:
    sources = load_docx_text_sources(source_path)
    if sources is None:
        return {
            "status": "not_applicable",
            "source_format": source_path.suffix.lower() if source_path else None,
            "target_count": 0,
            "patched_trailing_spaces": 0,
        }
    try:
        import fitz
    except ImportError as exc:
        raise AdapterError(
            "PDF_NORMALIZATION_FAILED",
            "PyMuPDF is required to preserve DOCX soft-wrap spaces",
            str(exc),
            503,
        ) from exc

    document = fitz.open(pdf_path)
    temporary = pdf_path.with_name(
        f".{pdf_path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        targets = _derive_soft_wrap_targets(document, sources)
        if not targets:
            return {
                "status": "no_changes",
                "source_format": ".docx",
                "target_count": 0,
                "patched_trailing_spaces": 0,
            }
        pending = _pending_pdf_lines(document, targets)
        patched = _patch_pdf_lines(document, pending)
        if patched != sum(targets.values()):
            raise AdapterError(
                "PDF_NORMALIZATION_FAILED",
                "soft-wrap space patch count differs from the derived target count",
                {"target_count": sum(targets.values()), "patched_count": patched},
            )
        document.save(temporary, garbage=4, deflate=True)
    finally:
        document.close()

    try:
        normalized = fitz.open(temporary)
        try:
            observed: Counter[tuple[int, str]] = Counter()
            for page_index, page in enumerate(normalized):
                for line in page.get_text().splitlines():
                    if line.endswith(" "):
                        observed[(page_index, line[:-1])] += 1
            missing = sum(
                max(0, count - observed[key]) for key, count in targets.items()
            )
        finally:
            normalized.close()
        if missing:
            raise AdapterError(
                "PDF_NORMALIZATION_FAILED",
                "saved PDF did not preserve every derived soft-wrap space",
                {"missing_count": missing},
            )
        temporary.replace(pdf_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "status": "applied",
        "source_format": ".docx",
        "target_count": sum(targets.values()),
        "patched_trailing_spaces": patched,
    }
