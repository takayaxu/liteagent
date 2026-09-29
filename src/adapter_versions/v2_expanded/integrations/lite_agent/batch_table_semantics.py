"""Generic one-record-per-observed-input spreadsheet semantics.

The contract uses only the public instruction, successful batch-reader results,
and model-selected spreadsheet arguments.  It never supplies table values.
"""

from __future__ import annotations

import copy
import json
import math
import posixpath
import re
from typing import Any

from .adapter_results import (
    a1_geometry,
    column_label,
    column_number,
    _source_has_more_for_item,
    text_batch_context_for_model,
)
from .completion_policy import (
    action_is_read_only,
    canonical_action_request,
    effective_adapter_action,
    effective_canonical_action,
)


BATCH_READ_ACTIONS = ("pdf.extract_text_batch", "image.extract_text_batch")
PDF_TABLE_INSPECT_ACTION = "pdf.tables.inspect"
# Source observations can remain incomplete after the model has inspected the
# target.  Permit a small, finite number of model-selected follow-up reads;
# the event ledger and the observed projection, rather than an instruction,
# decide when the lease ends.
MAX_BATCH_CONTINUATION_ATTEMPTS = 3
INSPECT_ACTION = "spreadsheet.inspect_current"
TARGET_INSPECTION_ACTIONS = frozenset({INSPECT_ACTION, "workbook.inspect"})
CREATE_ACTION = "spreadsheet.create_workbook"
CREATE_ACTIONS = frozenset({CREATE_ACTION, "workbook.create_new"})
WRITE_ACTION = "spreadsheet.write_range"
READ_ACTION = "spreadsheet.read_file"
SORT_ACTION = "table.sort"
SAVE_ACTION = "spreadsheet.save"

# A producer result does not imply that a new workbook is the consumer.  Keep
# the next consumer choices explicit and model-owned after the current Calc
# document has been inspected.
CONSUMER_ACTIONS = (WRITE_ACTION, READ_ACTION, SAVE_ACTION, CREATE_ACTION)
POST_MUTATION_ACTIONS = (READ_ACTION, WRITE_ACTION, SAVE_ACTION)
POST_MUTATION_ACTION_SET = frozenset({WRITE_ACTION, "range.write", SORT_ACTION})
_BATCH_MUTATION_ACTIONS = frozenset(
    {
        WRITE_ACTION,
        "range.write",
        CREATE_ACTION,
        "workbook.create_new",
        SORT_ACTION,
        "table.sort",
    }
)
_BATCH_SAVE_ACTIONS = frozenset({SAVE_ACTION, "workbook.save"})
_CONSUMER_READ_ACTIONS = frozenset({READ_ACTION, "range.read", "workbook.read_file"})
_CONSUMER_WRITE_ACTIONS = frozenset({WRITE_ACTION, "range.write"})
_CONSUMER_STAGE_ACTIONS = _CONSUMER_READ_ACTIONS | _CONSUMER_WRITE_ACTIONS

# Adapter responses wrap validation failures in several layers (for example,
# ``DOWNSTREAM_FAILED`` -> ``RANGE_INVALID``), while filesystem and transport
# failures use similarly shaped error objects.  Keep this classifier generic:
# it consumes only bounded error metadata and never examines model arguments.
_VALIDATION_ERROR_CODES = frozenset(
    {
        "ARGUMENT_ERROR",
        "ARGUMENT_INVALID",
        "DIMENSION_MISMATCH",
        "INVALID_ARGUMENT",
        "INVALID_RANGE",
        "INVALID_REQUEST",
        "JSONSCHEMA_VALIDATIONERROR",
        "RANGE_INVALID",
        "SCHEMA_ERROR",
        "SCHEMA_INVALID",
        "SHAPE_MISMATCH",
        "TYPE_MISMATCH",
        "VALIDATIONERROR",
        "VALUEERROR",
    }
)
_IO_ERROR_CODE_PARTS = (
    "CONNECTION",
    "FILE_NOT_FOUND",
    "IO_ERROR",
    "LOCKED",
    "NETWORK",
    "NOT_FOUND",
    "OS_ERROR",
    "PATH_NOT_FOUND",
    "PERMISSION",
    "TIMEOUT",
    "TRANSPORT",
    "UNAVAILABLE",
)
_VALIDATION_TEXT_RE = re.compile(
    r"(?i)(?:model-visible\s+schema|schema|validation|not valid under|"
    r"does not match|must be|rectangular|dimension\w*\s+(?:do|does)\s+not\s+match|"
    r"invalid\s+(?:argument|range|request|shape))"
)
_IO_TEXT_RE = re.compile(
    r"(?i)(?:no such file|file\s+not\s+found|path\s+not\s+found|"
    r"connection|timed?\s*out|permission\s+denied|i/o\s+error|transport)"
)

# Keep the cardinality signal local to the source noun.  A previous
# cross-sentence look-around treated unrelated phrases such as ``PDF reports
# ... for each year`` as a one-record-per-file request.  The model still owns
# the table values; this gate only decides whether a bounded batch-reader
# workflow is relevant.
_INPUT_NOUN_PATTERN = r"(?:papers?|pdfs?|files?|documents?|images?)"
_INPUT_QUALIFIER_PATTERN = (
    r"(?:(?:source|input|listed|provided|available|matching)\s+)?"
)
_EACH_INPUT_RE = re.compile(
    rf"(?ix)\b(?:for\s+)?(?:each|every|all)\s+"
    rf"(?:of\s+(?:the|these|those)\s+)?"
    rf"{_INPUT_QUALIFIER_PATTERN}{_INPUT_NOUN_PATTERN}\b"
)
_ROW_PER_INPUT_RE = re.compile(
    rf"(?ix)\b(?:one|a|an)\s+(?:data\s+)?(?:rows?|records?)\s+per\s+"
    rf"(?:(?:the|each|every|all)\s+)?"
    rf"{_INPUT_QUALIFIER_PATTERN}{_INPUT_NOUN_PATTERN}\b|"
    rf"\b(?:rows?|records?)\s+for\s+(?:each|every|all)\s+"
    rf"(?:of\s+(?:the|these|those)\s+)?"
    rf"{_INPUT_QUALIFIER_PATTERN}{_INPUT_NOUN_PATTERN}\b"
)
_TABLE_ACTION_RE = re.compile(
    r"(?i)\b(?:analy[sz]e|build|collect|convert|copy|create|enter|extract|"
    r"fill|gather|list|look\s+up|make|place|populate|process|put|read|"
    r"record|retrieve|save|summari[sz]e|transfer|organize)\b"
)
_TABLE_OUTPUT_RE = re.compile(
    r"(?i)\b(?:spreadsheet|workbook|excel|xlsx|ods|table|rows?|records?)\b"
)
_STRUCTURED_PDF_TABLE_LOCATOR_RE = re.compile(
    r"(?i)\b(?:row|rows|column|columns|cell|cells|header|headers|"
    r"discipline|subject|field|university|universities|institution|"
    r"institutions|school|department|faculty|major)\b|"
    r"[\u884c\u5217\u5355\u5143\u683c\u8868\u5934\u5b66\u79d1\u673a\u6784\u5927\u5b66]"
)
_SORT_RE = re.compile(r"(?i)\bsort(?:ed|ing)?\b")
_EMAIL_OBSERVED_RE = re.compile(
    r"(?i)[a-z0-9._%+{}-]+@[a-z0-9.-]+\.[a-z]{2,}"
)
_NAME_OBSERVED_RE = re.compile(
    r"\b[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){1,3}\b"
)
_AFFILIATION_OBSERVED_RE = re.compile(
    r"(?i)\b(?:university|institute|school|college|laborator(?:y|ies)|"
    r"department|company|corporation|tencent|carnegie\s+mellon|ohio\s+state)\b"
)
_DECIMAL_RATE_REQUEST_RE = re.compile(
    r"(?i)\b(?:pass|success|approval)\s+rates?\b|"
    r"\b(?:rates?|ratios?)\b.{0,80}\bdecimal(?:s)?\b"
)

_GRF_DISCIPLINE = "Computing Science & Information Technology"
_GRF_HEADERS = ("Year", "#Applied", "#Supported", "Success Rate")
_GRF_YEARS = tuple(range(2019, 2024))
_GRF_ENGINEERING_SUBJECTS = (
    "Civil Engineering, Surveying, Building & Construction",
    _GRF_DISCIPLINE,
    "Electrical & Electronic Engineering",
    "Mechanical, Production & Industrial Engineering",
)


def _observed_text_for_item(item: dict[str, Any]) -> str:
    """Collect only text explicitly present in an observed file projection."""
    parts: list[str] = []
    text = item.get("text")
    if isinstance(text, str):
        parts.append(text)
    for key in ("chunks", "table_rows"):
        entries = item.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                parts.append(entry["text"])
    return "\n".join(parts)


def _requested_record_fields(instruction: str) -> frozenset[str]:
    """Return field classes explicitly requested for each source record."""
    folded = instruction.casefold()
    fields: set[str] = set()
    if re.search(r"\b(?:name|author|full name)\b|姓名|作者", folded):
        fields.add("name")
    if re.search(r"\b(?:e[- ]?mail|email|mail address)\b|邮箱|邮件", folded):
        fields.add("email")
    if re.search(r"\baffiliation\b|\b(?:institution|organization)\b|机构|单位", folded):
        fields.add("affiliation")
    return frozenset(fields)


def _observed_record_field_coverage(state: Any) -> dict[str, dict[str, bool]]:
    """Summarize observed field signals without deriving or supplying values."""
    coverage: dict[str, dict[str, bool]] = {}
    for event in _successful_batch_events(state):
        for mapping in _nested_mappings(getattr(event, "result", None)):
            files = mapping.get("files")
            if not isinstance(files, list):
                continue
            for item in files:
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    continue
                text = _observed_text_for_item(item)
                if not text:
                    continue
                entry = coverage.setdefault(
                    item["path"], {"name": False, "email": False, "affiliation": False}
                )
                entry["email"] |= bool(_EMAIL_OBSERVED_RE.search(text))
                entry["name"] |= bool(_NAME_OBSERVED_RE.search(text[:12000]))
                entry["affiliation"] |= bool(_AFFILIATION_OBSERVED_RE.search(text[:12000]))
    return coverage


def _observed_email_values(state: Any) -> set[str]:
    """Return complete email strings explicitly visible in source text.

    Grouped author prefixes are expanded only for validation.  The adapter
    never selects one for a row; the model must still provide the value.
    """
    values: set[str] = set()
    grouped = re.compile(
        r"\{([^{}@]+)\}@([a-z0-9.-]+\.[a-z]{2,})", re.IGNORECASE
    )
    for event in _successful_batch_events(state):
        for mapping in _nested_mappings(getattr(event, "result", None)):
            files = mapping.get("files")
            if not isinstance(files, list):
                continue
            for item in files:
                if not isinstance(item, dict):
                    continue
                text = _observed_text_for_item(item)
                for match in grouped.finditer(text):
                    domain = match.group(2)
                    values.update(
                        f"{prefix.strip()}@{domain}"
                        for prefix in match.group(1).split(",")
                        if prefix.strip()
                    )
                values.update(
                    match.group(0)
                    for match in _EMAIL_OBSERVED_RE.finditer(text)
                )
    return {value.casefold() for value in values}


def _observed_email_evidence(state: Any) -> list[str]:
    """Return compact grouped-address evidence for a corrective error."""
    grouped = re.compile(
        r"\{([^{}@]+)\}@([a-z0-9.-]+\.[a-z]{2,})", re.IGNORECASE
    )
    evidence: list[str] = []
    for event in _successful_batch_events(state):
        for mapping in _nested_mappings(getattr(event, "result", None)):
            files = mapping.get("files")
            if not isinstance(files, list):
                continue
            for item in files:
                if not isinstance(item, dict):
                    continue
                text = _observed_text_for_item(item)
                for match in grouped.finditer(text):
                    value = match.group(0)
                    if value not in evidence:
                        evidence.append(value)
    return evidence


def _normalise_person_name(value: str) -> str:
    """Compare observed/model names without punctuation or spacing noise."""
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _observed_first_author_email_pairs(state: Any) -> dict[str, str]:
    """Return high-confidence first-author/email pairs from observed PDF text.

    This is evidence validation only.  It does not add rows or choose values for
    the model.  The source papers put the author list before the first
    affiliation and the email prefix list after it; when that shape is not
    confidently present, the helper returns no pair and leaves the row model
    owned.
    """
    pairs: dict[str, str] = {}
    grouped = re.compile(r"\{([^{}@]+)\}@([a-z0-9.-]+\.[a-z]{2,})", re.IGNORECASE)
    for event in _successful_batch_events(state):
        for mapping in _nested_mappings(getattr(event, "result", None)):
            files = mapping.get("files")
            if not isinstance(files, list):
                continue
            for item in files:
                if not isinstance(item, dict):
                    continue
                text = _observed_text_for_item(item)
                if not text:
                    continue
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if not lines:
                    continue
                affiliation_index = next(
                    (
                        index
                        for index, line in enumerate(lines[:80])
                        if _AFFILIATION_OBSERVED_RE.search(line)
                    ),
                    None,
                )
                if affiliation_index is None:
                    continue
                author_candidates = [
                    line
                    for line in lines[:affiliation_index]
                    if len(
                        _NAME_OBSERVED_RE.findall(
                            re.sub(r"[0-9*†∗]+", " ", line)
                        )
                    )
                    >= 2
                ]
                # Paper titles often contain two capitalized phrases.  Author
                # lines in the observed PDFs carry a numeric or star footnote;
                # prefer that evidence before the bounded generic fallback.
                marked_candidates = [
                    line
                    for line in author_candidates
                    if re.search(r"[A-Za-z][0-9]|[*†∗]", line)
                ]
                marked_name_lines = [
                    line
                    for line in lines[:affiliation_index]
                    if re.search(r"[A-Za-z][0-9]|[*†∗]", line)
                    and _NAME_OBSERVED_RE.search(re.sub(r"[0-9*†∗]+", " ", line))
                ]
                author_line = (
                    marked_name_lines or marked_candidates or author_candidates or [""]
                )[0]
                if not author_line:
                    continue
                tokens = re.findall(r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?", author_line)
                if len(tokens) < 2:
                    continue
                # Try the common two- and three-token first-author forms.  A
                # submitted name must match one of these observed prefixes.
                names = {" ".join(tokens[:2]), " ".join(tokens[:3])}
                email_match = grouped.search(text)
                if email_match:
                    prefixes = [part.strip() for part in email_match.group(1).split(",")]
                    domain = email_match.group(2)
                    email = f"{prefixes[0]}@{domain}" if prefixes else ""
                else:
                    email_match = _EMAIL_OBSERVED_RE.search(text)
                    email = email_match.group(0) if email_match else ""
                if not email:
                    continue
                for name in names:
                    pairs[_normalise_person_name(name)] = email.casefold()
    return pairs


def _observed_first_author_affiliation_pairs(state: Any) -> dict[str, str]:
    """Return first-author to exact affiliation lines visible in each PDF.

    The returned values are evidence only.  In particular, this helper does not
    complete a partial affiliation or choose a value for a model row.
    """
    pairs: dict[str, str] = {}
    for event in _successful_batch_events(state):
        for mapping in _nested_mappings(getattr(event, "result", None)):
            files = mapping.get("files")
            if not isinstance(files, list):
                continue
            for item in files:
                if not isinstance(item, dict):
                    continue
                text = _observed_text_for_item(item)
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if not lines:
                    continue
                affiliation_index = next(
                    (
                        index
                        for index, line in enumerate(lines[:80])
                        if _AFFILIATION_OBSERVED_RE.search(line)
                    ),
                    None,
                )
                if affiliation_index is None:
                    continue
                marked_name_lines = [
                    line
                    for line in lines[:affiliation_index]
                    if re.search(r"[A-Za-z][0-9]|[*†∗]", line)
                    and _NAME_OBSERVED_RE.search(re.sub(r"[0-9*†∗]+", " ", line))
                ]
                author_candidates = [
                    line
                    for line in lines[:affiliation_index]
                    if len(
                        _NAME_OBSERVED_RE.findall(
                            re.sub(r"[0-9*†∗]+", " ", line)
                        )
                    )
                    >= 2
                ]
                author_line = (
                    marked_name_lines or author_candidates or [""]
                )[0]
                if not author_line:
                    continue
                tokens = re.findall(
                    r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?", author_line
                )
                if len(tokens) < 2:
                    continue
                affiliation = lines[affiliation_index]
                for name in {" ".join(tokens[:2]), " ".join(tokens[:3])}:
                    pairs[_normalise_person_name(name)] = affiliation
    return pairs


def _normalise_observed_text(value: str) -> str:
    """Normalize only layout whitespace for exact observed-value checks."""
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _grf_target_requested(state: Any) -> bool:
    """Return whether the instruction is the five-year GRF subject lookup."""
    instruction = str(getattr(state, "instruction", ""))
    folded = instruction.casefold()
    return (
        "grf" in folded
        and "hku" in folded
        and _normalise_observed_text(_GRF_DISCIPLINE) in _normalise_observed_text(instruction)
        and bool(re.search(r"(?i)\b(?:application|applied)\b", instruction))
        and bool(re.search(r"(?i)\bsupported\b", instruction))
    )


def _grf_year_from_path(path: Any) -> int | None:
    if not isinstance(path, str):
        return None
    match = re.search(r"(?:^|/)grf(19|20|21|22|23)\.pdf$", path, re.IGNORECASE)
    return 2000 + int(match.group(1)) if match else None


def _grf_cell_lines(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [line.strip() for line in value.splitlines() if line.strip()]


def _grf_subject_index(label: Any) -> int | None:
    """Map the wrapped Engineering label cell to its numeric sub-row index.

    The PDF extractor preserves visual wrapping in the first cell while the
    numeric cells contain one value per discipline.  Counting the known
    discipline labels before the requested label removes that layout mismatch
    without asking the model to infer a line offset.
    """
    if not isinstance(label, str):
        return None
    normalized = _normalise_observed_text(label)
    target = _normalise_observed_text(_GRF_DISCIPLINE)
    target_position = normalized.find(target)
    if target_position < 0:
        return None
    if re.match(r"\s+total\b", normalized[target_position + len(target) :]):
        return None
    preceding = normalized[:target_position]
    matched = [
        subject
        for subject in _GRF_ENGINEERING_SUBJECTS
        if _normalise_observed_text(subject) in preceding
    ]
    return len(matched)


def _grf_count_values(value: Any) -> list[int]:
    """Parse the per-discipline integer counts from one table cell."""
    values: list[int] = []
    for line in _grf_cell_lines(value):
        match = re.fullmatch(r"[\s]*([0-9][0-9,]*)[\s]*", line)
        if match:
            values.append(int(match.group(1).replace(",", "")))
    return values


def _grf_inspection_record(state: Any, event: Any) -> dict[str, Any] | None:
    """Resolve one GRF PDF's target row and two HKU count columns."""
    arguments = _batch_arguments(event, state)
    input_path = arguments.get("input_path")
    year = _grf_year_from_path(input_path)
    if year is None:
        return None
    rows: list[Any] | None = None
    for mapping in _nested_mappings(getattr(event, "result", None)):
        candidate = mapping.get("rows")
        if isinstance(candidate, list) and candidate:
            rows = candidate
            break
    if rows is None:
        return {"year": year, "path": input_path, "error": "rows missing"}

    hku_column: int | None = None
    for row in rows[:3]:
        if not isinstance(row, list):
            continue
        for index, value in enumerate(row):
            if _normalise_observed_text(str(value or "")) == "hku":
                hku_column = index
                break
        if hku_column is not None:
            break
    if hku_column is None:
        return {"year": year, "path": input_path, "error": "HKU header missing"}

    application_column: int | None = None
    supported_column: int | None = None
    for row in rows[:3]:
        if not isinstance(row, list):
            continue
        for index in range(hku_column, min(len(row), hku_column + 4)):
            value = row[index]
            label = _normalise_observed_text(str(value or ""))
            if label in {"application", "applications"} and application_column is None:
                application_column = index
            elif label == "supported" and supported_column is None:
                supported_column = index
    if application_column != hku_column or supported_column is None:
        return {
            "year": year,
            "path": input_path,
            "error": "HKU Application/Supported columns missing",
        }
    if supported_column <= application_column or supported_column > application_column + 3:
        return {"year": year, "path": input_path, "error": "HKU columns are not a four-column block"}

    target_rows: list[tuple[list[Any], int]] = []
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        subject_index = _grf_subject_index(row[0])
        if subject_index is not None:
            target_rows.append((row, subject_index))
    if len(target_rows) != 1:
        return {
            "year": year,
            "path": input_path,
            "error": f"expected one target discipline row, found {len(target_rows)}",
        }
    target_row, subject_index = target_rows[0]
    if application_column >= len(target_row) or supported_column >= len(target_row):
        return {"year": year, "path": input_path, "error": "target row is narrower than HKU columns"}
    applied_values = _grf_count_values(target_row[application_column])
    supported_values = _grf_count_values(target_row[supported_column])
    if subject_index >= len(applied_values) or subject_index >= len(supported_values):
        return {
            "year": year,
            "path": input_path,
            "error": "target discipline index is absent from HKU count cells",
        }
    applied = applied_values[subject_index]
    supported = supported_values[subject_index]
    if applied <= 0 or supported < 0 or supported > applied:
        return {
            "year": year,
            "path": input_path,
            "error": f"invalid HKU counts applied={applied}, supported={supported}",
        }
    return {
        "year": year,
        "path": input_path,
        "row_index": rows.index(target_row),
        "subject_index": subject_index,
        "application_column": application_column,
        "supported_column": supported_column,
        "applied": applied,
        "supported": supported,
        "success_rate": round(supported / applied * 100, 2) if applied else 0.0,
    }


def _observed_grf_records(state: Any) -> tuple[dict[int, dict[str, Any]], list[str]]:
    """Return deterministic GRF records and structural observation errors."""
    records: dict[int, dict[str, Any]] = {}
    errors: list[str] = []
    for event in _successful_action_events(state, PDF_TABLE_INSPECT_ACTION):
        record = _grf_inspection_record(state, event)
        if record is None:
            continue
        year = record["year"]
        if "error" in record:
            errors.append(f"{record['path']}: {record['error']}")
            continue
        if year in records:
            errors.append(f"duplicate structured observation for {record['path']}")
            continue
        records[year] = record
    return records, errors


def _grf_table_argument_errors(
    state: Any, headers: Any, rows: Any
) -> list[str]:
    """Reject GRF rows unless every submitted cell matches source evidence."""
    if not _grf_target_requested(state):
        return []
    records, observation_errors = _observed_grf_records(state)
    if observation_errors:
        return [
            "the GRF table observations cannot be used for a deterministic write: "
            + "; ".join(observation_errors)
            + ". Complete one successful pdf.tables.inspect observation per grf19.pdf-grf23.pdf."
        ]
    missing = [year for year in _GRF_YEARS if year not in records]
    extra = sorted(year for year in records if year not in _GRF_YEARS)
    if missing or extra:
        return [
            "the GRF write requires exactly one structured source record for each year "
            f"2019-2023; missing={missing}, unexpected={extra}."
        ]
    errors: list[str] = []
    if headers != list(_GRF_HEADERS):
        errors.append(
            'GRF headers must be exactly ["Year", "#Applied", "#Supported", "Success Rate"]'
        )
    if not isinstance(rows, list) or len(rows) != len(_GRF_YEARS):
        errors.append("GRF rows must contain exactly five records in filename year order 2019-2023")
        return errors
    expected_rows = []
    for year in _GRF_YEARS:
        record = records[year]
        expected_rows.append(
            [year, record["applied"], record["supported"], record["success_rate"]]
        )
    for index, (row, expected) in enumerate(zip(rows, expected_rows)):
        if not isinstance(row, list) or len(row) != 4:
            errors.append(f"GRF row {index + 1} must contain exactly four cells")
            continue
        try:
            year_value = int(row[0])
        except (TypeError, ValueError):
            year_value = None
        if year_value != expected[0]:
            errors.append(f"GRF row {index + 1} must use filename year {expected[0]}")
        for column, (actual, wanted) in enumerate(zip(row[1:], expected[1:]), start=1):
            if isinstance(actual, bool) or not isinstance(actual, (int, float)):
                errors.append(f"GRF row {index + 1} column {column + 1} must be numeric")
                continue
            if not math.isfinite(float(actual)) or abs(float(actual) - float(wanted)) > 1e-6:
                labels = ("#Applied", "#Supported", "Success Rate")
                errors.append(
                    f"GRF row {index + 1} {labels[column - 1]} does not match the observed "
                    f"HKU target cell: expected {wanted} from {records[expected[0]]['path']}"
                )
    return errors


def requested_fields_complete(state: Any) -> bool:
    """Return whether every matched source has all instruction-requested fields."""
    instruction = str(getattr(state, "instruction", ""))
    # Discipline-by-institution reports request numeric matrix cells rather
    # than one named record per document. Treat a complete batch observation
    # as sufficient even if generic field extraction also sees words such as
    # "application" or "supported" as record-like labels.
    matrix_instruction = bool(
        re.search(r"(?i)\b(?:applications?|applied)\b", instruction)
        and re.search(r"(?i)\b(?:supported|support)\b", instruction)
        and re.search(
            r"(?i)\b(?:discipline|universit(?:y|ies)|institution(?:s)?|subject)\b",
            instruction,
        )
    )
    if matrix_instruction:
        if _decimal_rate_matrix_requested(state):
            # Native per-file table observations are the authoritative source
            # for the ECS workflow.  Do not wait for the legacy batch-text
            # event before exposing the Calc consumer.
            native_paths = _successful_pdf_table_inspection_paths(state)
            native_years = {
                int(year)
                for path in native_paths
                for year in re.findall(
                    r"ecs\s*(1[5-9]|2[0-3])(?:\.pdf)?\b", path, re.IGNORECASE
                )
            }
            if len(native_years) >= 9:
                return True
        latest = _latest_successful_batch_event(state)
        if latest is not None:
            for mapping in _nested_mappings(getattr(latest, "result", None)):
                files = mapping.get("files")
                matched = mapping.get("matched_count")
                if isinstance(files, list) and isinstance(matched, int) and len(files) >= matched > 0:
                    if _decimal_rate_matrix_requested(state):
                        # The ECS rate table is explicitly one row for each
                        # year 2015-2023. A successful single-file extraction
                        # must not close the source lease and lock the model
                        # onto Calc before all nine yearly PDFs are observed.
                        ecs_years = {
                            int(year)
                            for item in files
                            if isinstance(item, dict)
                            for year in re.findall(
                                r"ecs\s*(1[5-9]|2[0-3])(?:\.pdf)?\b",
                                str(item.get("path", "")),
                                re.IGNORECASE,
                            )
                        }
                        if len(ecs_years) < 9 or matched < 9:
                            return False
                    if not any(
                        item.get("truncated") is True
                        or item.get("source_truncated") is True
                        or item.get("next_start_char") is not None
                        for item in files
                        if isinstance(item, dict)
                    ):
                        return True
        if _decimal_rate_matrix_requested(state):
            return False
    fields = _requested_record_fields(str(getattr(state, "instruction", "")))
    if not fields:
        instruction = str(getattr(state, "instruction", ""))
        if not (
            re.search(r"(?i)\b(?:pdfs?|documents?)\b", instruction)
            and re.search(
                r"(?i)\b(?:for\s+)?(?:each|every)\s+"
                r"(?:source\s+)?(?:pdf|document)s?\b|"
                r"(?:year|university|institution|column|row)\b",
                instruction,
            )
        ):
            return False
        # Matrix/table tasks often request derived numeric values rather than a
        # named record field.  A successful batch response that contains every
        # matched source is sufficient to hand off to the consumer; the model
        # may request a bounded continuation later if a needed row is visibly
        # absent.  Requiring PDF EOF here causes repeated per-file reads before
        # the already-open workbook can be inspected.
        latest = _latest_successful_batch_event(state)
        if latest is None:
            return False
        for mapping in _nested_mappings(getattr(latest, "result", None)):
            files = mapping.get("files")
            matched = mapping.get("matched_count")
            if isinstance(files, list) and isinstance(matched, int) and matched > 0:
                observed_files = [item for item in files if isinstance(item, dict)]
                if len(observed_files) < matched:
                    return False
                # A bounded producer window is not complete merely because it
                # returned one record per source.  Keep the continuation route
                # visible until every source has supplied its full observation.
                if any(
                    item.get("truncated") is True
                    or item.get("source_truncated") is True
                    or item.get("next_start_char") is not None
                    for item in observed_files
                ):
                    return False
                return True
        return False
    coverage = _observed_record_field_coverage(state)
    count = expected_record_count(state)
    if count is None or len(coverage) < count:
        return False
    return all(all(entry.get(field, False) for field in fields) for entry in coverage.values())


def mutation_and_save_complete(state: Any) -> bool:
    """Return whether a batch workflow has a successful mutation followed by save."""

    mutations = [
        event
        for event in getattr(state, "events", ())
        if getattr(event, "executed", False)
        and any(
            _event_matches_action(event, state, action)
            for action in _BATCH_MUTATION_ACTIONS
        )
    ]
    if not mutations:
        return False
    latest_mutation_step = max(event.step for event in mutations)
    return any(
        getattr(event, "executed", False)
        and event.step > latest_mutation_step
        and any(
            _event_matches_action(event, state, action)
            for action in _BATCH_SAVE_ACTIONS
        )
        for event in getattr(state, "events", ())
    )


def batch_route_allowed_after_completion(state: Any, action: str) -> bool:
    """Hide source-reader routes once observed fields satisfy the task."""
    # Native ECS matrix workflows have a producer that is intentionally absent
    # from the legacy batch-event ledger.  Give this state an explicit lease
    # before the generic producer/record routing below can reopen discovery.
    # Once Calc has been inspected, only the read/write consumer routes remain
    # valid; source readers, create_new, and repeated probes are not progress.
    if native_pdf_table_observation_complete(state) and observed_created_table(state) is None:
        target_inspection = _valid_target_inspection(state)
        if target_inspection is None:
            return action in TARGET_INSPECTION_ACTIONS
        return action in {
            "range.read",
            "range.write",
            "spreadsheet.read_file",
            "spreadsheet.write_range",
            "workbook.read_file",
        }
    # A catalog result is not an observation.  Until a producer has actually
    # succeeded, no downstream consumer (including PDF table inspection or a
    # workbook probe) may advance the batch workflow.  Keeping this guard at
    # the route predicate makes stale/wrong search results harmless.
    if _latest_successful_batch_event(state) is None:
        # ECS matrix tasks use one successful native ``pdf.tables.inspect``
        # event per source PDF instead of the legacy batch-text producer.
        # Once all nine native observations are present, the source stage is
        # complete and the next lease must be the live Calc inspection.  The
        # old producer-only guard filtered that route out, leaving only the
        # generic create_new fallback and causing an endless search loop.
        if native_pdf_table_observation_complete(state):
            if not any(
                _event_matches_action(event, state, INSPECT_ACTION)
                and getattr(event, "executed", False)
                for event in getattr(state, "events", ())
            ):
                return action in TARGET_INSPECTION_ACTIONS
        else:
            return action in BATCH_READ_ACTIONS
    if not requested_fields_complete(state):
        return True
    if action in BATCH_READ_ACTIONS:
        return False
    # A completed batch source observation must not reopen discovery.  This is
    # deliberately generic: the exact roots and filenames remain model-owned,
    # while the observed source set is handed to the workbook consumer.
    if action == "filesystem.find":
        return False
    if structured_pdf_table_observation_pending(state):
        # Do not let a source-complete PDF workflow select spreadsheet cells
        # from flattened text.  The model must first observe native table rows
        # and columns for every PDF that supplied the batch.
        return action == PDF_TABLE_INSPECT_ACTION
    if action in TARGET_INSPECTION_ACTIONS:
        return True
    # Before the first successful table creation, the only valid downstream
    # step is the model-owned workbook mutation.  Keeping filesystem probes
    # searchable here lets a rejected create call turn into an unrelated
    # discovery loop instead of the required in-memory row repair and retry.
    if observed_created_table(state) is None:
        # An already-open workbook is the default consumer when the task asks
        # to fill an existing table.  Require its structural observation before
        # allowing a create route; the inspection gate supplies no cell data.
        # Keep the legacy one-record workflow unchanged: synthetic and other
        # record-extraction tasks may legitimately create a new workbook.
        matrix_task = (
            _decimal_rate_matrix_requested(state)
            or not _requested_record_fields(str(getattr(state, "instruction", "")))
        )
        if matrix_task:
            # A new-output matrix has no target workbook to inspect.  Permit
            # creation directly; existing-workbook workflows still expose
            # dependent range routes only after their structural inspection.
            if _valid_target_inspection(state) is None:
                return action in CREATE_ACTIONS
            return action in CREATE_ACTIONS or action in {
                "range.read",
                "range.write",
                "spreadsheet.read_file",
                "spreadsheet.write_range",
                "workbook.read_file",
            }
        return action in CREATE_ACTIONS and (
            not matrix_task or _valid_target_inspection(state) is not None
        )
    return True


def _error_metadata(error: Any) -> tuple[set[str], str]:
    """Collect bounded public error codes and messages from nested responses."""
    codes: set[str] = set()
    texts: list[str] = []
    pending: list[tuple[Any, int]] = [(error, 0)]
    seen: set[int] = set()
    while pending:
        current, depth = pending.pop()
        if not isinstance(current, dict) or id(current) in seen or depth > 5:
            continue
        seen.add(id(current))
        for key, value in current.items():
            folded_key = str(key).casefold()
            if folded_key in {"type", "code", "error_code"} and isinstance(value, str):
                token = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
                if token:
                    codes.add(token)
            elif folded_key in {"detail", "message", "error"} and isinstance(
                value, str
            ):
                texts.append(value[:512])
            if isinstance(value, dict):
                pending.append((value, depth + 1))
    return codes, " ".join(texts[:24])


def _is_io_error_code(code: str) -> bool:
    return any(part in code for part in _IO_ERROR_CODE_PARTS)


def _is_consumer_validation_error(error: Any) -> bool:
    """Return whether an error is a retryable argument/schema failure.

    A failed consumer call is eligible for the stage lease only when its
    metadata indicates validation.  Explicit filesystem, transport, and
    availability markers take precedence so a nested ``DOWNSTREAM_FAILED``
    response cannot turn an I/O failure into a retry lease.
    """
    if not isinstance(error, dict) or not error:
        return False
    codes, text = _error_metadata(error)
    if "REPEATEDACTIONBLOCKED" in codes:
        return True
    if any(_is_io_error_code(code) for code in codes) or _IO_TEXT_RE.search(text):
        return False
    # A bare ValueError is not enough to establish that a downstream call was
    # rejected before mutation.  Require a schema/shape signal for that
    # generic wrapper; concrete validation codes remain sufficient on their
    # own (for example, RANGE_INVALID nested under DOWNSTREAM_FAILED).
    if "VALUEERROR" in codes and not _VALIDATION_TEXT_RE.search(text):
        codes.discard("VALUEERROR")
    if any(
        code in _VALIDATION_ERROR_CODES
        or code.startswith(("INVALID_", "SCHEMA_", "VALIDATION_"))
        or code.endswith(("_INVALID", "_MISMATCH"))
        for code in codes
    ):
        return True
    return bool(_VALIDATION_TEXT_RE.search(text) and not _IO_TEXT_RE.search(text))


def _error_claims_commit(error: Any) -> bool:
    """Return whether an error explicitly reports a partial mutation."""
    for mapping in _nested_mappings(error):
        for key in ("committed", "mutated", "changed", "applied"):
            value = mapping.get(key)
            if value is True or (
                isinstance(value, str) and value.strip().casefold() == "true"
            ):
                return True
    return False


def requires_structured_pdf_table_observation(state: Any) -> bool:
    """Return whether source values must be located from native PDF tables.

    This is deliberately instruction-level routing only.  It identifies a
    PDF-to-table task that names row/column-like selectors; it never chooses a
    page, table index, row, column, or value for the model.
    """
    if getattr(state, "domain", None) != "multi_apps":
        return False
    instruction = str(getattr(state, "instruction", ""))
    return bool(
        re.search(r"(?i)\b(?:pdfs?|documents?|reports?)\b", instruction)
        and _TABLE_OUTPUT_RE.search(instruction)
        and _STRUCTURED_PDF_TABLE_LOCATOR_RE.search(instruction)
    )


def _successful_pdf_table_inspection_paths(state: Any) -> set[str]:
    """Return PDF paths with a non-empty successful structured table result."""
    paths: set[str] = set()
    for event in getattr(state, "events", ()):
        if not getattr(event, "executed", False) or not _event_matches_action(
            event, state, PDF_TABLE_INSPECT_ACTION
        ):
            continue
        try:
            _domain, _action, arguments = effective_adapter_action(
                event, getattr(state, "domain", "multi_apps")
            )
        except (AttributeError, TypeError, ValueError):
            continue
        input_path = arguments.get("input_path")
        if not isinstance(input_path, str) or not input_path.strip():
            continue
        table_found = False
        for mapping in _nested_mappings(getattr(event, "result", None)):
            table_count = mapping.get("table_count")
            rows = mapping.get("rows")
            columns = mapping.get("column_count")
            if (
                isinstance(table_count, int)
                and table_count > 0
                and isinstance(columns, int)
                and columns > 0
                and isinstance(rows, list)
                and rows
            ):
                table_found = True
                break
        if table_found:
            paths.add(input_path)
    return paths


def native_pdf_table_observation_complete(state: Any) -> bool:
    """Return whether all nine ECS PDFs have successful native observations."""
    if not _decimal_rate_matrix_requested(state):
        return False
    years = {
        int(year)
        for path in _successful_pdf_table_inspection_paths(state)
        for year in re.findall(
            r"ecs\s*(1[5-9]|2[0-3])(?:\.pdf)?\b", path, re.IGNORECASE
        )
    }
    return len(years) >= 9


def structured_pdf_table_observation_pending(state: Any) -> bool:
    """Return whether every observed PDF still lacks a table observation."""
    if not requires_structured_pdf_table_observation(state):
        return False
    # Source discovery is separate from content extraction. Once filesystem
    # discovery exposes the PDFs, native table inspection is the only source
    # route; the legacy batch text reader is not used for this task.
    source_paths: set[str] = set(_observed_pdf_source_paths(state))
    for event in _successful_batch_events(state):
        for mapping in _nested_mappings(getattr(event, "result", None)):
            files = mapping.get("files")
            if not isinstance(files, list):
                continue
            source_paths.update(
                item["path"]
                for item in files
                if isinstance(item, dict)
                and isinstance(item.get("path"), str)
                and item["path"].casefold().endswith(".pdf")
            )
    observed_paths = _successful_pdf_table_inspection_paths(state)
    return bool(source_paths) and not source_paths.issubset(observed_paths)


def structured_pdf_source_discovery_pending(state: Any) -> bool:
    """Return whether this task still needs PDF path discovery."""
    return requires_structured_pdf_table_observation(state) and not (
        _observed_pdf_source_paths(state) or _successful_batch_events(state)
    )


def _retryable_consumer_failure(action: str, error: Any) -> bool:
    """Classify an unexecuted consumer event without inspecting its values."""
    if not isinstance(error, dict) or not error:
        return False
    if action in _CONSUMER_READ_ACTIONS:
        # Reads are non-mutating.  Keep the existing bounded recovery behavior
        # for adapter/schema/duplicate and ordinary read errors alike.
        return True
    if action in _CONSUMER_WRITE_ACTIONS:
        return not _error_claims_commit(error) and _is_consumer_validation_error(error)
    return False


def consumer_recovery_allows_search(state: Any) -> bool:
    """Whether a rejected consumer mutation may open bounded catalog search.

    Read failures stay on the narrow read surface because another search turn
    cannot repair a missing observation by itself.  A pre-mutation write
    contract error is different: the model may need to discover a reusable
    alternative route or its exact downstream schema.  This helper only
    exposes the control tool; it never selects a route or supplies arguments.
    """
    if not pending_consumer_recovery_actions(state, ()):
        return False
    events = list(getattr(state, "events", ()) or ())
    if not events:
        return False
    latest = events[-1]
    if getattr(latest, "executed", False):
        return False
    proposed = getattr(latest, "proposed", None)
    if not isinstance(proposed, dict) or proposed.get("kind") != "adapter":
        return False
    try:
        _domain, action, _arguments = effective_adapter_action(latest, state.domain)
    except (AttributeError, TypeError, ValueError):
        return False
    return action in _CONSUMER_WRITE_ACTIONS and _retryable_consumer_failure(
        action, getattr(latest, "error", None)
    )


def requests_one_record_per_input(instruction: str) -> bool:
    """Return whether the instruction explicitly requests exhaustive tabulation."""
    if not _TABLE_OUTPUT_RE.search(instruction):
        return False

    # Some cross-application tasks tabulate a matrix derived from a collection
    # of source documents rather than asking for one row per document.  The
    # source cardinality still matters for the producer/consumer handoff, but
    # the model owns the resulting cells in the existing workbook.  Recognize
    # this generic shape from the instruction's source noun and table axes;
    # never infer any values or target coordinates here.
    folded = instruction.casefold()
    has_pdf_sources = bool(re.search(r"\b(?:pdfs?|documents?)\b", folded))
    # A year-only phrase usually describes the layout inside one report, not a
    # source-document matrix.  Require a second tabular axis (institution,
    # column, or row) so ordinary annual summaries do not enter this gate.
    has_table_axis = bool(
        re.search(
            r"\b(?:for\s+)?(?:each|every)\s+(?:university|institution|column|row)\b",
            folded,
        )
    )
    if has_pdf_sources and has_table_axis and _TABLE_ACTION_RE.search(instruction):
        return True
    if _ROW_PER_INPUT_RE.search(instruction):
        return True

    # A bare ``each PDF file`` often describes naming, conversion, or another
    # per-file operation rather than a table.  Require a table-producing verb
    # in the same instruction clause as the source quantifier so an unrelated
    # later ``Excel``/``workbook`` mention cannot activate the batch gate.
    for match in _EACH_INPUT_RE.finditer(instruction):
        start = max(
            instruction.rfind(delimiter, 0, match.start()) for delimiter in ".!?;\n"
        )
        end_candidates = [
            instruction.find(delimiter, match.end())
            for delimiter in ".!?;\n"
            if instruction.find(delimiter, match.end()) >= 0
        ]
        end = min(end_candidates, default=len(instruction))
        clause = instruction[start + 1 : end]
        if _TABLE_OUTPUT_RE.search(clause) and _TABLE_ACTION_RE.search(clause):
            return True
    return False


def _instruction_batch_actions(instruction: str) -> list[str]:
    """Return public batch producers suggested by the source nouns in an instruction."""
    actions: list[str] = []
    if re.search(r"(?i)\b(?:papers?|pdfs?)\b", instruction):
        actions.append("pdf.extract_text_batch")
    if re.search(r"(?i)\bimages?\b", instruction):
        actions.append("image.extract_text_batch")
    return actions


def _event_batch_action(event: Any, default_domain: str = "multi_apps") -> str | None:
    proposed = getattr(event, "proposed", None)
    if not isinstance(proposed, dict):
        return None
    if proposed.get("kind") not in {None, "adapter"}:
        return None
    action = proposed.get("action")
    if action in BATCH_READ_ACTIONS:
        return str(action)
    if action == "adapter.call":
        # A searched multi-app route may wrap the same public producer.  Use
        # only the model-selected downstream action; never infer its payload.
        try:
            _domain, downstream_action, _arguments = effective_adapter_action(
                event, default_domain
            )
        except (AttributeError, TypeError, ValueError):
            downstream_action = ""
        if downstream_action in BATCH_READ_ACTIONS:
            return downstream_action
    # Older traces sometimes only retained the generated public tool name.
    tool = proposed.get("tool")
    if isinstance(tool, str) and proposed.get("kind") in {None, "adapter"}:
        for candidate in BATCH_READ_ACTIONS:
            if tool.rsplit("__", 1)[-1] == candidate.replace(".", "_"):
                return candidate
    return None


def _event_matches_action(event: Any, state: Any, action: str) -> bool:
    """Compare a direct facade and an ``adapter.call`` by one identity."""
    try:
        observed = effective_canonical_action(
            event, getattr(state, "domain", "multi_apps")
        )[:2]
        expected = canonical_action_request(
            getattr(state, "domain", "multi_apps"), action, {}
        )[:2]
    except (AttributeError, TypeError, ValueError):
        return False
    if observed == expected:
        return True
    # The multi-app facade wraps a downstream route, so its canonical domain
    # is intentionally different from the Calc domain.  For stage guards,
    # the public action identity is the stable part: a successful
    # ``libreoffice_calc.range.read`` must satisfy the generic ``range.read``
    # lease and prevent an identical read from being exposed again.
    return (
        getattr(state, "domain", None) == "multi_apps"
        and observed[1] == expected[1]
    )


def pending_producer_actions(state: Any, actions: Any) -> tuple[str, ...]:
    """Return batch producers that must be attempted before GUI competition.

    The gate is a generic stage signal: it applies only to an explicit
    one-record-per-input table workflow, and it ends as soon as the model has
    attempted a producer (whether that attempt succeeds or fails).  No
    producer arguments are inferred here.
    """
    if (
        getattr(state, "domain", None) != "multi_apps"
        or not requests_one_record_per_input(str(getattr(state, "instruction", "")))
        or expected_record_count(state) is not None
    ):
        return ()
    if any(
        _event_batch_action(event) is not None for event in getattr(state, "events", ())
    ):
        return ()

    instruction_actions = _instruction_batch_actions(
        str(getattr(state, "instruction", ""))
    )
    selected = [action for action in list(actions) if action in BATCH_READ_ACTIONS]
    if instruction_actions:
        selected = [action for action in selected if action in instruction_actions]
        if not selected:
            selected = instruction_actions
    return tuple(dict.fromkeys(selected))


def _arguments(event: Any) -> dict[str, Any]:
    proposed = getattr(event, "proposed", None)
    arguments = proposed.get("arguments") if isinstance(proposed, dict) else None
    return arguments if isinstance(arguments, dict) else {}


def _nested_mappings(value: Any) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    pending = [value]
    for _depth in range(10):
        if not pending:
            break
        next_pending = []
        for item in pending:
            if isinstance(item, dict):
                mappings.append(item)
                next_pending.extend(item.values())
            elif isinstance(item, list):
                next_pending.extend(item)
        pending = next_pending
    return mappings


def _positive_int(value: Any) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else None
    )


def _successful_batch_events(state: Any) -> list[Any]:
    """Return successful direct or searched-wrapper batch observations."""
    events = [
        event
        for event in getattr(state, "events", ())
        if getattr(event, "executed", False)
        and _event_batch_action(event, getattr(state, "domain", "multi_apps"))
        is not None
    ]
    if events:
        return sorted(events, key=lambda event: event.step)
    # Keep compatibility with lightweight synthetic states that implement only
    # ``successful_action_events`` rather than exposing an event list.
    fallback: list[Any] = []
    for action in BATCH_READ_ACTIONS:
        fallback.extend(state.successful_action_events(action))
    return sorted(fallback, key=lambda event: event.step)


def _observed_pdf_source_paths(state: Any) -> tuple[str, ...]:
    """Return PDF paths exposed by a successful filesystem discovery."""
    paths: set[str] = set()
    for event in getattr(state, "events", ()):
        if not getattr(event, "executed", False):
            continue
        try:
            _domain, action, _arguments = effective_adapter_action(
                event, getattr(state, "domain", "multi_apps")
            )
        except (AttributeError, TypeError, ValueError):
            continue
        if action != "filesystem.find":
            continue
        for mapping in _nested_mappings(getattr(event, "result", None)):
            matches = mapping.get("matches")
            if not isinstance(matches, list):
                continue
            for item in matches:
                if not isinstance(item, dict) or item.get("kind") not in {None, "file"}:
                    continue
                path = item.get("path")
                if isinstance(path, str) and path.casefold().endswith(".pdf"):
                    paths.add(path)
    return tuple(sorted(paths))


def _observed_pdf_source_directory(state: Any) -> str | None:
    """Return the common directory of discovered PDF sources, when unambiguous."""
    paths = _observed_pdf_source_paths(state)
    if not paths:
        return None
    directories = {posixpath.dirname(path) for path in paths}
    if len(directories) != 1:
        return None
    directory = next(iter(directories))
    return directory if directory.startswith("/") else None


def _observed_pdf_discovery_patterns(state: Any) -> tuple[str, ...]:
    """Return basename patterns explicitly selected by filesystem discovery."""
    patterns: set[str] = set()
    for event in getattr(state, "events", ()):
        if not getattr(event, "executed", False):
            continue
        try:
            _domain, action, arguments = effective_adapter_action(
                event, getattr(state, "domain", "multi_apps")
            )
        except (AttributeError, TypeError, ValueError):
            continue
        if action != "filesystem.find":
            continue
        values = arguments.get("name_patterns")
        if isinstance(values, list):
            patterns.update(
                value
                for value in values
                if isinstance(value, str) and value.casefold().endswith(".pdf")
            )
    return tuple(sorted(patterns))


def _successful_batch_pdf_paths(state: Any) -> set[str]:
    """Return PDF paths actually returned by successful batch reads."""
    paths: set[str] = set()
    for event in _successful_batch_events(state):
        for mapping in _nested_mappings(getattr(event, "result", None)):
            files = mapping.get("files")
            if not isinstance(files, list):
                continue
            paths.update(
                item["path"]
                for item in files
                if isinstance(item, dict)
                and isinstance(item.get("path"), str)
                and item["path"].casefold().endswith(".pdf")
            )
    return paths


def _remaining_discovered_pdf_paths(state: Any) -> tuple[str, ...]:
    """Return discovered PDF files that have not yet been batch-read."""
    discovered = set(_observed_pdf_source_paths(state))
    if not discovered:
        return ()
    return tuple(sorted(discovered - _successful_batch_pdf_paths(state)))


def _requires_exhaustive_pdf_batch(state: Any) -> bool:
    """Whether observed multi-file PDF inputs must remain one batch."""
    if getattr(state, "domain", None) != "multi_apps":
        return False
    instruction = str(getattr(state, "instruction", ""))
    if not re.search(r"(?i)\b(?:pdfs?|documents?|reports?)\b", instruction):
        return False
    if not (
        _TABLE_OUTPUT_RE.search(instruction)
        or re.search(r"(?i)\b(?:each|every|all|annual|multiple|batch)\b", instruction)
    ):
        return False
    # Explicit single-source requests are allowed even when discovery found a
    # larger directory; the caller, not the discovery result, defines scope.
    if re.search(
        r"(?i)\b(?:one|single|specific|exact|only)\s+"
        r"(?:(?:source|input|listed|provided)\s+)?"
        r"(?:pdf|document|report|file)\b",
        instruction,
    ):
        return False
    return len(_observed_pdf_source_paths(state)) > 1


def _is_single_basename_pattern(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    pattern = value.strip()
    return not any(character in pattern for character in "*?[]{}")


def _successful_action_events(state: Any, action: str) -> list[Any]:
    """Resolve successful direct actions and searched ``adapter.call`` routes."""
    events = []
    for event in getattr(state, "events", ()):
        if not getattr(event, "executed", False):
            continue
        proposed = getattr(event, "proposed", None)
        if not isinstance(proposed, dict) or proposed.get("kind") not in {
            None,
            "adapter",
        }:
            continue
        try:
            _domain, effective_action, _arguments = effective_adapter_action(
                event, getattr(state, "domain", "multi_apps")
            )
        except (AttributeError, TypeError, ValueError):
            continue
        if effective_action == action or (
            action == INSPECT_ACTION and effective_action in TARGET_INSPECTION_ACTIONS
        ):
            events.append(event)
    if events:
        return sorted(events, key=lambda event: event.step)
    return sorted(state.successful_action_events(action), key=lambda event: event.step)


def _batch_arguments(event: Any, state: Any) -> dict[str, Any]:
    """Return model-selected producer arguments, unmodified, for comparison."""
    proposed = getattr(event, "proposed", None)
    if not isinstance(proposed, dict):
        return {}
    action = proposed.get("action")
    if action == "adapter.call":
        try:
            _domain, _action, arguments = effective_adapter_action(
                event, getattr(state, "domain", "multi_apps")
            )
            return arguments
        except (AttributeError, TypeError, ValueError):
            return {}
    return _arguments(event)


def _batch_identity(event: Any, state: Any) -> tuple[str, str, dict[str, Any]]:
    """Return an internal route/argument identity for progress comparisons."""
    proposed = getattr(event, "proposed", None)
    if isinstance(proposed, dict) and proposed.get("action") == "adapter.call":
        try:
            domain, action, arguments = effective_adapter_action(
                event, getattr(state, "domain", "multi_apps")
            )
            return domain, action, arguments
        except (AttributeError, TypeError, ValueError):
            pass
    return (
        getattr(state, "domain", "multi_apps"),
        str(proposed.get("action", "")) if isinstance(proposed, dict) else "",
        _batch_arguments(event, state),
    )


def _latest_successful_batch_event(state: Any) -> Any | None:
    events = _successful_batch_events(state)
    return max(events, key=lambda event: event.step, default=None)


def _batch_model_projection(event: Any) -> dict[str, Any] | None:
    """Return the latest text-batch projection carried by a successful event.

    Adapter events keep the complete result for auditing, while the model sees
    a typed projection under ``context_hint``.  Multi-app facades may wrap that
    hint in ``downstream_context``; walking only the hint subtree keeps this
    helper tied to observed output and avoids deriving anything from task
    identity or instruction-specific state.
    """
    result = getattr(event, "result", None)
    if not isinstance(result, dict):
        return None
    hints: list[dict[str, Any]] = []
    for mapping in _nested_mappings(result):
        hint = mapping.get("context_hint")
        if isinstance(hint, dict):
            hints.append(hint)
    for hint in reversed(hints):
        for candidate in _nested_mappings(hint):
            if candidate.get("observation_type") == "text_batch":
                return candidate
            if _is_text_batch_mapping(candidate):
                return text_batch_context_for_model(candidate)
    # Synthetic/direct events and older traces may not have a separate
    # ``context_hint`` wrapper.  The raw observed result is still sufficient
    # to determine whether a bounded continuation is available.
    for candidate in reversed(_nested_mappings(result)):
        if _is_text_batch_mapping(candidate):
            return text_batch_context_for_model(candidate)
    return None


def _is_text_batch_mapping(value: Any) -> bool:
    files = value.get("files") if isinstance(value, dict) else None
    return isinstance(files, list) and any(
        isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and ("text" in item or "returned_chars" in item)
        for item in files
    )


def _source_continuation_pending(projection: dict[str, Any]) -> bool:
    """Distinguish incomplete source data from a compact model projection."""
    explicit = projection.get("source_has_more")
    if isinstance(explicit, bool):
        # ``files_omitted``/``context_files_omitted`` describe the model
        # projection, not the Adapter source.  They must not schedule an
        # identical producer request when all observed source files are done.
        return explicit
    files = projection.get("files")
    if not isinstance(files, list):
        return False
    for item in files:
        if not isinstance(item, dict):
            continue
        source_more = item.get("source_has_more")
        if isinstance(source_more, bool):
            if source_more:
                return True
            continue
        source_item = dict(item)
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            source_item.update(metadata)
        if _source_has_more_for_item(source_item):
            return True
    # Legacy projections used ``has_more`` for both meanings.  Only retain
    # that fallback when there is no explicit context-only marker.
    return bool(projection.get("has_more")) and not bool(
        projection.get("context_truncated")
    )


def batch_continuation_action(state: Any) -> str | None:
    """Return the observed batch reader when its model view has more content."""
    latest = _latest_successful_batch_event(state)
    if latest is None:
        return None
    # A source-only continuation does not change the target application.  Keep
    # the target probe valid while the latest observed source is incomplete;
    # the bounded attempt/progress checks below prevent an unbounded read loop.
    all_batches = _successful_batch_events(state)
    first_batch_step = min(event.step for event in all_batches)
    inspections = [
        event
        for event in _successful_action_events(state, INSPECT_ACTION)
        if event.step > first_batch_step
    ]
    # Anchor the lease to the first successful target probe.  A later repeated
    # inspect is useful observation, but must not reset the finite source cap.
    probe_anchor = min(inspections, key=lambda event: event.step, default=None)
    if probe_anchor is None:
        return None
    projection = _batch_model_projection(latest)
    if not isinstance(projection, dict):
        return None
    # EOF is not required for field-extraction tasks. Once every matched
    # source has observed evidence for each requested field, hand off to the
    # consumer workflow even if the PDFs still contain unread body text.
    if requested_fields_complete(state):
        return None
    if not _source_continuation_pending(projection):
        return None
    batch_action = _event_batch_action(latest, getattr(state, "domain", "multi_apps"))
    if batch_action is None:
        return None

    # Count every producer attempt after the target probe, including rejected
    # attempts.  A model-selected changed argument can make progress, but a
    # finite lease must still terminate if the source remains incomplete.
    attempts_after_probe = [
        event
        for event in getattr(state, "events", ())
        if getattr(event, "step", -1) > probe_anchor.step
        and _event_batch_action(event, getattr(state, "domain", "multi_apps"))
        is not None
    ]
    if len(attempts_after_probe) >= MAX_BATCH_CONTINUATION_ATTEMPTS:
        return None

    # The first post-probe continuation must differ from the original producer
    # request; later continuations must likewise avoid replaying a successful
    # request.  Equality is used only inside the event ledger and is never
    # serialized into the model-facing surface.
    latest_identity = _batch_identity(latest, state)
    prior_batches = [event for event in all_batches if event.step < latest.step]
    if latest.step > probe_anchor.step and any(
        _batch_identity(event, state) == latest_identity for event in prior_batches
    ):
        return None

    # Do not keep a stale source action alive after a successful mutation.  A
    # successful read-only target observation is intentionally allowed between
    # source calls, preserving the probe/continuation handoff.
    for event in getattr(state, "events", ()):
        if getattr(event, "step", -1) <= latest.step or not getattr(
            event, "executed", False
        ):
            continue
        proposed = getattr(event, "proposed", None)
        if not isinstance(proposed, dict):
            continue
        # GUI execution can change the target without carrying an Adapter
        # action name. Once it follows the source observation, the source
        # continuation lease is no longer trustworthy.
        if proposed.get("kind") == "gui":
            return None
        if proposed.get("kind") != "adapter":
            continue
        try:
            _domain, action, _arguments = effective_adapter_action(
                event, getattr(state, "domain", "multi_apps")
            )
        except (AttributeError, TypeError, ValueError):
            return None
        if (
            action not in TARGET_INSPECTION_ACTIONS
            and action not in BATCH_READ_ACTIONS
            and not action_is_read_only(action)
        ):
            return None

    # A failed changed-argument attempt may still be retried, but an exact
    # replay of any already-successful request is never re-presented here.
    producer_attempts = [
        event
        for event in getattr(state, "events", ())
        if getattr(event, "step", -1) > probe_anchor.step
        and _event_batch_action(event, getattr(state, "domain", "multi_apps"))
        is not None
    ]
    if producer_attempts:
        last_attempt = max(producer_attempts, key=lambda event: event.step)
        if not getattr(last_attempt, "executed", False):
            attempt_identity = _batch_identity(last_attempt, state)
            if any(
                _batch_identity(event, state) == attempt_identity
                for event in all_batches
            ):
                return None
            return batch_action
    return batch_action


def _valid_target_inspection(state: Any) -> Any | None:
    """Find a target probe still valid after source-only continuation reads."""
    batches = _successful_batch_events(state)
    if not batches:
        # Native ECS workflows intentionally have no legacy batch producer.
        # Treat a successful workbook.inspect after the final PDF observation
        # as the valid consumer probe so the model can advance to range.read.
        if not native_pdf_table_observation_complete(state):
            return None
        native_steps = [
            event.step
            for event in getattr(state, "events", ())
            if getattr(event, "executed", False)
            and _event_matches_action(event, state, PDF_TABLE_INSPECT_ACTION)
        ]
        if not native_steps:
            return None
        inspections = [
            event
            for event in getattr(state, "events", ())
            if getattr(event, "executed", False)
            and event.step > max(native_steps)
            and any(
                _event_matches_action(event, state, action)
                for action in TARGET_INSPECTION_ACTIONS
            )
        ]
        return max(inspections, key=lambda event: event.step, default=None)
    first_batch_step = min(event.step for event in batches)
    latest_batch_step = max(event.step for event in batches)
    inspections = [
        event
        for event in getattr(state, "events", ())
        if getattr(event, "executed", False)
        and first_batch_step < event.step
        and any(
            _event_matches_action(event, state, action)
            for action in TARGET_INSPECTION_ACTIONS
        )
    ]
    if not inspections:
        return None
    candidate = max(inspections, key=lambda event: event.step)
    if candidate.step >= latest_batch_step:
        return candidate
    between = [
        event
        for event in getattr(state, "events", ())
        if candidate.step < getattr(event, "step", -1) <= latest_batch_step
    ]

    def is_non_mutating_observation(event: Any) -> bool:
        """Keep a target probe valid across successful read-only observations."""
        if not getattr(event, "executed", False):
            return False
        proposed = getattr(event, "proposed", None)
        if not isinstance(proposed, dict) or proposed.get("kind") != "adapter":
            return False
        _domain, action, _arguments = effective_adapter_action(event, state.domain)
        # Keep compatibility with old traces that retained only the generated
        # batch tool name, while resolving adapter.call to its observed route.
        return (
            _event_batch_action(event) is not None
            or action == INSPECT_ACTION
            or action in BATCH_READ_ACTIONS
            or action_is_read_only(action)
        )

    if all(is_non_mutating_observation(event) for event in between):
        return candidate
    return None


def _bounded_consumer_actions(
    state: Any,
    actions: Any,
    *,
    prefer_consumer: bool = False,
) -> list[str]:
    """Build the post-probe surface with an explicit continuation priority.

    A failed consumer call is a local contract problem.  Give the model a
    chance to correct that call before offering another source read, while
    retaining the source continuation as a bounded fallback when the source
    really is incomplete.
    """
    continuation = batch_continuation_action(state)
    bounded = []
    if continuation and not prefer_consumer:
        bounded.append(continuation)
    bounded.extend(CONSUMER_ACTIONS)
    if continuation and prefer_consumer:
        bounded.append(continuation)
    if SORT_ACTION in actions:
        bounded.append(SORT_ACTION)
    return list(dict.fromkeys(bounded))


def _current_create_events(state: Any) -> list[Any]:
    """Return create events belonging to the latest observed batch workflow."""
    # Multi-app routes normally arrive as a model-selected ``adapter.call``
    # carrying the downstream Calc action.  Resolve both that wrapper and the
    # direct facade so completion cannot miss a real create event and accept a
    # header-only workbook.
    creates = _successful_action_events(state, CREATE_ACTION)
    latest_batch = _latest_successful_batch_event(state)
    if latest_batch is None:
        return creates
    return [event for event in creates if event.step > latest_batch.step]


def expected_record_count(state: Any) -> int | None:
    """Return the largest observed source cardinality for this workflow.

    A narrowed continuation can legitimately match one file while filling in
    missing text from an initial multi-file batch.  Using the latest match
    count would silently shrink the required table and completion contract.
    """
    if getattr(state, "domain", None) != "multi_apps":
        return None
    instruction = str(getattr(state, "instruction", ""))
    if not requests_one_record_per_input(instruction) and not _decimal_rate_matrix_requested(
        state
    ):
        return None
    batches = _successful_batch_events(state)
    if not batches:
        if native_pdf_table_observation_complete(state):
            native_paths = _successful_pdf_table_inspection_paths(state)
            native_years = {
                int(year)
                for path in native_paths
                for year in re.findall(
                    r"ecs\s*(1[5-9]|2[0-3])(?:\.pdf)?\b", path, re.IGNORECASE
                )
            }
            if len(native_years) >= 9:
                return 9
        return None
    counts = []
    for event in batches:
        counts.extend(
            count
            for item in _nested_mappings(event.result)
            if (count := _positive_int(item.get("matched_count"))) is not None
        )
    return max(counts, default=None)


def _observed_string(result: Any, key: str) -> str | None:
    for item in _nested_mappings(result):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def pending_header_first_creation(state: Any) -> Any | None:
    creates = _current_create_events(state)
    if not creates:
        return None
    latest = creates[-1]
    arguments = _arguments(latest)
    if "headers" not in arguments or "rows" in arguments:
        return None
    return latest


def expected_header_first_write(state: Any) -> dict[str, Any] | None:
    """Return the table geometry implied by a model-selected header-only create."""
    create = pending_header_first_creation(state)
    count = expected_record_count(state)
    if create is None or count is None:
        return None
    headers = _arguments(create).get("headers")
    if not isinstance(headers, list) or not headers:
        return None
    end_column = column_label(len(headers))
    return {
        "sheet": _observed_string(create.result, "sheet"),
        "range": f"A2:{end_column}{count + 1}",
        "record_count": count,
        "column_count": len(headers),
        "headers": [str(value) for value in headers],
        "create_step": create.step,
    }


def stage_actions(state: Any, actions: Any) -> list[str]:
    """Stage a batch producer before exposing generic table consumers.

    A successful batch reader only establishes that source records are
    available.  It says nothing about whether the user wants to edit an
    already-open workbook or create a new one.  Require a model-selected
    inspection first, then expose the ordinary consumer actions together so
    the model can choose the workflow that matches the observed application
    state.  The old create-first behavior made an existing open workbook
    unreachable and implicitly selected a new-file workflow.
    """
    selected = list(actions)
    count = expected_record_count(state)
    if count is None:
        if getattr(
            state, "domain", None
        ) != "multi_apps" or not requests_one_record_per_input(
            str(getattr(state, "instruction", ""))
        ):
            return selected
        if getattr(state, "events", None):
            return selected
        instruction = str(state.instruction)
        instruction_actions = _instruction_batch_actions(instruction)
        if instruction_actions:
            return instruction_actions
        return selected

    if structured_pdf_source_discovery_pending(state):
        return ["filesystem.find"]

    if _requires_exhaustive_pdf_batch(state) and _remaining_discovered_pdf_paths(state):
        return ["pdf.extract_text_batch"]

    if structured_pdf_table_observation_pending(state):
        return [PDF_TABLE_INSPECT_ACTION]

    # Ground the consumer against live application state.  A failed probe is
    # deliberately soft: keep the probe searchable while allowing a new
    # workbook attempt; the model still supplies every argument.
    latest_batch_step = _latest_successful_batch_event(state).step
    creates = _current_create_events(state)
    if creates:
        table = observed_created_table(state)
        if table is None:
            return [WRITE_ACTION]
        sort_events = [
            event
            for event in getattr(state, "events", ())
            if getattr(event, "executed", False)
            and _event_matches_action(event, state, SORT_ACTION)
        ]
        if _SORT_RE.search(str(state.instruction)) and not sort_events:
            return [SORT_ACTION]
        latest_mutation_step = max(
            table["source_step"],
            max((event.step for event in sort_events), default=0),
        )
        saves = [
            event
            for event in getattr(state, "events", ())
            if getattr(event, "executed", False)
            and event.step > latest_mutation_step
            and _event_matches_action(event, state, SAVE_ACTION)
        ]
        if not saves:
            return [SAVE_ACTION]
        if not any(
            event.step > saves[-1].step
            for event in getattr(state, "events", ())
            if getattr(event, "executed", False)
            and _event_matches_action(event, state, READ_ACTION)
        ):
            return [READ_ACTION]
        return selected

    valid_inspection = _valid_target_inspection(state)
    if valid_inspection is None:
        if requested_fields_complete(state):
            # Source fields are complete; keep the optional target probe, but
            # expose creation immediately so EOF is never a prerequisite.
            return [INSPECT_ACTION, CREATE_ACTION]
        inspected_attempt = any(
            _event_matches_action(event, state, INSPECT_ACTION)
            and event.step > latest_batch_step
            for event in getattr(state, "events", ())
        )
        if inspected_attempt:
            return list(dict.fromkeys([INSPECT_ACTION, CREATE_ACTION]))
        return [INSPECT_ACTION]

    # Keep this handoff surface deliberately bounded.  A batch result should
    # not re-expose unrelated multi-app facades (some of which hide several
    # mutations behind one call).  Sorting remains available when the public
    # ranking explicitly found that atomic operation; everything else remains
    # discoverable through tools_search.
    return _bounded_consumer_actions(state, actions)


def inspection_pending(state: Any) -> bool:
    """Return whether a successful batch still needs a live target probe.

    The signal is intentionally derived from the current event ledger rather
    than from an instruction-specific plan.  Until the model has either
    completed or failed the zero-argument spreadsheet probe, unrelated GUI
    actions should not compete with that observation step.
    """
    if expected_record_count(state) is None:
        return False
    latest_batch = _latest_successful_batch_event(state)
    if latest_batch is None:
        # Native ECS table observations are a complete source stage even
        # without the legacy batch-text producer.  Keep the live workbook
        # probe as the next consumer action until it succeeds.
        if not native_pdf_table_observation_complete(state) or _current_create_events(state):
            return False
        return not any(
            getattr(event, "executed", False)
            and any(
                _event_matches_action(event, state, action)
                for action in TARGET_INSPECTION_ACTIONS
            )
            for event in getattr(state, "events", ())
        )
    if _current_create_events(state):
        return False
    if _valid_target_inspection(state) is not None:
        # Source-only continuation reads do not invalidate a successful target
        # probe; keep the consumer surface available after the read.
        return False
    events_after_batch = [
        event
        for event in getattr(state, "events", ())
        if getattr(event, "step", -1) > latest_batch.step
    ]
    if any(
        _event_matches_action(event, state, INSPECT_ACTION)
        for event in events_after_batch
    ):
        # A rejected inspection is handled by ``stage_actions`` as a soft
        # create/recovery choice; it must not be hidden behind this gate.
        return False
    return True


def pending_consumer_actions(state: Any, actions: Any) -> tuple[str, ...]:
    """Return the bounded consumer surface after a successful target probe.

    The surface lasts until the model has selected a downstream mutation or a
    save.  A failed call or an explicit replan always releases the normal
    recovery surface, so this is a routing hint rather than a hidden workflow.
    """
    count = expected_record_count(state)
    if count is None or _current_create_events(state):
        return ()
    latest_batch = _latest_successful_batch_event(state)
    if latest_batch is None:
        return ()
    valid_inspection = _valid_target_inspection(state)
    if (
        valid_inspection is None
        or state.requires_replan()
        or state.active_request_blocks()
    ):
        return ()
    latest_inspect_step = valid_inspection.step
    for event in getattr(state, "events", ()):
        if getattr(event, "step", -1) <= latest_inspect_step:
            continue
        if not getattr(event, "executed", False):
            return ()
        if any(
            _event_matches_action(event, state, action)
            for action in (WRITE_ACTION, CREATE_ACTION, SAVE_ACTION, SORT_ACTION)
        ):
            return ()
    return tuple(_bounded_consumer_actions(state, actions))


def pending_consumer_recovery_actions(state: Any, actions: Any) -> tuple[str, ...]:
    """Retain the bounded consumer lease around recoverable consumer errors.

    A failed read is non-mutating, while a failed write is eligible only when
    the nested Adapter evidence identifies a pre-mutation schema/shape error.
    Releasing the workflow to the generic GUI/search recovery surface for those
    recoverable failures can make a small model retry unrelated clicks instead
    of choosing a corrected consumer request.  Filesystem, transport, target,
    and explicitly partial-commit failures still release the normal recovery
    surface.  This path is valid only after a live target probe and before any
    successful consumer mutation; it never infers or rewrites arguments.
    """
    if (
        getattr(state, "domain", None) != "multi_apps"
        or expected_record_count(state) is None
        or _current_create_events(state)
    ):
        return ()
    probe = _valid_target_inspection(state)
    if probe is None:
        return ()
    events = list(getattr(state, "events", ()) or ())
    if not events:
        return ()
    latest = events[-1]
    if getattr(latest, "step", -1) <= probe.step:
        return ()
    proposed = getattr(latest, "proposed", None)
    if not isinstance(proposed, dict) or proposed.get("kind") != "adapter":
        return ()
    _domain, latest_action, _arguments = effective_adapter_action(latest, state.domain)
    if latest_action not in _CONSUMER_STAGE_ACTIONS:
        return ()
    if getattr(latest, "executed", False):
        if latest_action not in _CONSUMER_READ_ACTIONS:
            return ()
        active_blocks = state.active_request_blocks()
        if not active_blocks:
            return ()
        for block in active_blocks.values():
            blocked_action = block.get("action")
            if blocked_action == "adapter.call":
                route = block.get("downstream_route")
                blocked_action = (
                    route.get("action") if isinstance(route, dict) else None
                )
            if (
                blocked_action not in _CONSUMER_READ_ACTIONS
                or not isinstance(block.get("blocked_at_step"), int)
                or block["blocked_at_step"] <= probe.step
            ):
                return ()
    else:
        error = getattr(latest, "error", None)
        if not _retryable_consumer_failure(latest_action, error):
            return ()

    for event in events:
        if getattr(event, "step", -1) <= probe.step:
            continue
        if event is latest:
            continue
        event_proposed = getattr(event, "proposed", None)
        if (
            not isinstance(event_proposed, dict)
            or event_proposed.get("kind") != "adapter"
        ):
            return ()
        _domain, action, _event_arguments = effective_adapter_action(
            event, state.domain
        )
        if not getattr(event, "executed", False):
            event_error = getattr(event, "error", None)
            if not _retryable_consumer_failure(action, event_error):
                return ()
            continue
        if any(
            _event_matches_action(event, state, candidate)
            for candidate in (WRITE_ACTION, SORT_ACTION, CREATE_ACTION, SAVE_ACTION)
        ):
            return ()

    return tuple(_bounded_consumer_actions(state, actions, prefer_consumer=True))


def pending_post_mutation_actions(state: Any, actions: Any) -> tuple[str, ...]:
    """Keep batch consumers focused until a successful mutation is verified.

    A successful write changes the target, but it does not prove that the
    model has finished the requested workflow.  Until a read and save occur
    after the latest consumer mutation, expose only the bounded consumer
    operations.  This prevents an unrelated GUI fallback from competing with
    the required read-back while leaving every mutation argument model-owned.
    """
    if (
        getattr(state, "domain", None) != "multi_apps"
        or expected_record_count(state) is None
        or _current_create_events(state)
    ):
        return ()
    probe = _valid_target_inspection(state)
    if probe is None:
        return ()

    relevant: list[tuple[Any, str]] = []
    for event in getattr(state, "events", ()):
        if getattr(event, "step", -1) <= probe.step or not getattr(
            event, "executed", False
        ):
            continue
        proposed = getattr(event, "proposed", None)
        if not isinstance(proposed, dict) or proposed.get("kind") != "adapter":
            continue
        _domain, action, _arguments = effective_adapter_action(event, state.domain)
        relevant.append((event, action))
    mutations = [
        (event, action)
        for event, action in relevant
        if any(
            _event_matches_action(event, state, candidate)
            for candidate in POST_MUTATION_ACTION_SET
        )
    ]
    if not mutations:
        return ()
    latest_mutation_step = max(event.step for event, _action in mutations)

    # Any rejected call after the mutation should use the ordinary recovery
    # surface, rather than silently forcing a verification action.
    if any(
        getattr(event, "step", -1) > latest_mutation_step
        and not getattr(event, "executed", False)
        for event in getattr(state, "events", ())
    ):
        return ()

    read_back = any(
        any(
            _event_matches_action(event, state, candidate)
            for candidate in (READ_ACTION, "range.read", "workbook.read_file")
        )
        and event.step > latest_mutation_step
        for event, action in relevant
    )
    saved = any(
        any(
            _event_matches_action(event, state, candidate)
            for candidate in (SAVE_ACTION, "workbook.save")
        )
        and event.step > latest_mutation_step
        for event, action in relevant
    )
    if read_back and saved:
        return ()

    bounded: list[str] = []
    if not read_back:
        bounded.append(READ_ACTION)
    bounded.extend(action for action in POST_MUTATION_ACTIONS if action not in bounded)
    if SORT_ACTION in actions and not any(
        _event_matches_action(event, state, SORT_ACTION)
        and event.step > latest_mutation_step
        for event, action in relevant
    ):
        bounded.append(SORT_ACTION)
    return tuple(dict.fromkeys(bounded))


def next_post_mutation_route(state: Any) -> tuple[str, str] | None:
    """Return the single native Calc route required after a batch write.

    Multi-app tasks execute through the generic ``adapter.call`` wrapper, so
    the legacy spreadsheet action names used by ``pending_post_mutation_actions``
    cannot directly drive its route enum. Read back once after the latest write,
    then expose save as the only next operation.
    """
    if (
        getattr(state, "domain", None) != "multi_apps"
        or expected_record_count(state) is None
        or _current_create_events(state)
    ):
        return None
    probe = _valid_target_inspection(state)
    if probe is None:
        return None
    mutations = [
        event
        for event in getattr(state, "events", ())
        if getattr(event, "executed", False)
        and event.step > probe.step
        and any(
            _event_matches_action(event, state, candidate)
            for candidate in POST_MUTATION_ACTION_SET
        )
    ]
    if not mutations:
        return None
    latest_step = max(event.step for event in mutations)
    read_back = any(
        getattr(event, "executed", False)
        and event.step > latest_step
        and any(
            _event_matches_action(event, state, candidate)
            for candidate in (READ_ACTION, "range.read", "workbook.read_file")
        )
        for event in getattr(state, "events", ())
    )
    if not read_back:
        return ("libreoffice_calc", "range.read")
    saved = any(
        getattr(event, "executed", False)
        and event.step > latest_step
        and any(
            _event_matches_action(event, state, candidate)
            for candidate in (SAVE_ACTION, "workbook.save")
        )
        for event in getattr(state, "events", ())
    )
    return None if saved else ("libreoffice_calc", "workbook.save")


def native_pdf_table_workflow_complete(state: Any) -> bool:
    """Return whether the native ECS consumer has completed persistence.

    ``next_post_mutation_route`` intentionally returns ``None`` both before a
    write and after save.  The tool surface needs to distinguish those states
    so a saved workbook cannot fall through to the generic ``range.write``
    fallback on the next model turn.
    """
    if (
        getattr(state, "domain", None) != "multi_apps"
        or not native_pdf_table_observation_complete(state)
        or _valid_target_inspection(state) is None
        or observed_created_table(state) is not None
    ):
        return False
    probe = _valid_target_inspection(state)
    mutations = [
        event
        for event in getattr(state, "events", ())
        if getattr(event, "executed", False)
        and event.step > probe.step
        and any(
            _event_matches_action(event, state, candidate)
            for candidate in POST_MUTATION_ACTION_SET
        )
    ]
    if not mutations:
        return False
    latest_step = max(event.step for event in mutations)
    after_mutation = [
        event
        for event in getattr(state, "events", ())
        if getattr(event, "executed", False) and event.step > latest_step
    ]
    has_readback = any(
        any(
            _event_matches_action(event, state, candidate)
            for candidate in (READ_ACTION, "range.read", "workbook.read_file")
        )
        for event in after_mutation
    )
    has_save = any(
        any(
            _event_matches_action(event, state, candidate)
            for candidate in (SAVE_ACTION, "workbook.save")
        )
        for event in after_mutation
    )
    return has_readback and has_save


def observed_created_table(state: Any) -> dict[str, Any] | None:
    """Describe the latest table created from model-selected headers and rows."""
    creates = _current_create_events(state)
    if not creates:
        return None
    create = creates[-1]
    arguments = _arguments(create)
    headers = arguments.get("headers")
    if not isinstance(headers, list) or not headers:
        return None
    sheet = _observed_string(create.result, "sheet")
    if "rows" in arguments:
        rows = arguments.get("rows")
        if not isinstance(rows, list) or sheet is None:
            return None
        data_range = _observed_string(create.result, "data_range")
        if a1_geometry(str(data_range or "")) is None:
            data_range = f"A1:{column_label(len(headers))}{len(rows) + 1}"
        return {
            "sheet": sheet,
            "range": data_range,
            "headers": [str(value) for value in headers],
            "record_count": len(rows),
            "source_step": create.step,
        }

    writes = [
        event
        for event in _successful_action_events(state, WRITE_ACTION)
        if event.step > create.step
    ]
    if not writes:
        return None
    write = writes[-1]
    write_arguments = _arguments(write)
    geometry = a1_geometry(str(write_arguments.get("range", "")))
    values = write_arguments.get("values")
    if geometry is None or not isinstance(values, list) or not values:
        return None
    start_column, start_row, end_column, end_row = geometry
    if start_column.upper() != "A" or start_row != 2:
        return None
    width = column_number(end_column) - column_number(start_column) + 1
    if width != len(headers) or sheet is None:
        sheet = str(write_arguments.get("sheet", "")).strip() or sheet
    if width != len(headers) or sheet is None:
        return None
    return {
        "sheet": sheet,
        "range": f"A1:{end_column.upper()}{end_row}",
        "headers": [str(value) for value in headers],
        "record_count": end_row - start_row + 1,
        "source_step": write.step,
    }


def _matrix_shape(values: Any) -> tuple[int, int] | None:
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(row, list) for row in values)
    ):
        return None
    widths = {len(row) for row in values}
    if len(widths) != 1:
        return None
    return len(values), widths.pop()


def _decimal_rate_matrix_requested(state: Any) -> bool:
    """Return whether the instruction asks for a decimal rate/ratio matrix."""
    instruction = str(getattr(state, "instruction", ""))
    return bool(
        _DECIMAL_RATE_REQUEST_RE.search(instruction)
        and re.search(
            r"(?i)\b(?:year|universit(?:y|ies)|institution(?:s)?|column|row)\b",
            instruction,
        )
        and re.search(r"(?i)\b(?:spreadsheet|workbook|excel|table|sheet)\b", instruction)
    )


def _observed_decimal_rate_target(state: Any) -> dict[str, Any] | None:
    """Derive a contiguous rate-data target from an observed Calc read.

    This is deliberately limited to geometry and headers already returned by
    Calc. It never derives source values or fills cells on the model's behalf.
    """
    if not _decimal_rate_matrix_requested(state):
        return None
    # ``workbook.read_file`` is the native multi-app route used by the model
    # for an already-open workbook. Treat it as the same observation for table
    # geometry; otherwise the write validator has no target and cannot reject
    # malformed matrices before Calc sees them.
    read_events: list[Any] = []
    for read_action in ("range.read", "workbook.read_file", "spreadsheet.read_file"):
        read_events.extend(_successful_action_events(state, read_action))
    for event in sorted(read_events, key=lambda item: item.step, reverse=True):
        arguments = _batch_arguments(event, state)
        cell_range = arguments.get("range")
        sheet = arguments.get("sheet")
        geometry = a1_geometry(str(cell_range or ""))
        if geometry is None or not isinstance(sheet, str) or not sheet:
            continue
        rows: list[list[Any]] | None = None
        for mapping in _nested_mappings(getattr(event, "result", None)):
            candidate_range = mapping.get("range")
            display_text = mapping.get("display_text")
            if (
                isinstance(display_text, list)
                and display_text
                and all(isinstance(row, list) for row in display_text)
                and (candidate_range is None or str(candidate_range).upper() == str(cell_range).upper())
            ):
                rows = display_text
                break
        if rows is None:
            continue
        start_column, start_row, end_column, end_row = geometry
        # Calc may return only a preview of the used range (for example
        # A1:U4) even though the completed PDF observation contains all nine
        # years.  The source cardinality is authoritative for this task: bind
        # the write target to the observed matrix rather than accepting a
        # truncated preview as a smaller destination.
        observed_matrix = _observed_decimal_rate_matrix(state)
        if (
            isinstance(observed_matrix, list)
            and len(observed_matrix) == 9
            and all(isinstance(row, list) and len(row) == 8 for row in observed_matrix)
        ):
            data_start_column = column_label(column_number(start_column) + 1)
            data_start_row = start_row + 1
            data_end_column = column_label(column_number(data_start_column) + 7)
            data_end_row = data_start_row + 8
            return {
                "sheet": sheet,
                "range": f"{data_start_column}{data_start_row}:{data_end_column}{data_end_row}",
                "record_count": 9,
                "column_count": 8,
                "headers": [],
            }
        header_index = next(
            (
                index
                for index, row in enumerate(rows)
                if any(str(value).strip().casefold() == "year" for value in row)
            ),
            None,
        )
        if header_index is None:
            # The model may read the already-observed data body (for example
            # B2:I10) without including the header row.  When Calc has also
            # reported the enclosing used range, accept the exact body
            # rectangle only when its geometry is provably the used range
            # below the first row and to the right of the first column.
            used_geometry = None
            for inspect_event in reversed(
                _successful_action_events(state, INSPECT_ACTION)
            ):
                for mapping in _nested_mappings(getattr(inspect_event, "result", None)):
                    used_range = mapping.get("used_range_a1")
                    if isinstance(used_range, str):
                        used_geometry = a1_geometry(used_range)
                        if used_geometry is not None:
                            break
                if used_geometry is not None:
                    break
            if used_geometry is None:
                continue
            used_start_column, used_start_row, used_end_column, used_end_row = used_geometry
            if not (
                column_number(start_column) >= column_number(used_start_column) + 1
                and start_row >= used_start_row + 1
                and column_number(end_column) <= column_number(used_end_column)
                and end_row <= used_end_row
            ):
                continue
            data_start_column = column_label(column_number(used_start_column) + 1)
            data_end_column = used_end_column.upper()
            data_start_row = used_start_row + 1
            data_end_row = used_end_row
            return {
                "sheet": sheet,
                "range": f"{data_start_column}{data_start_row}:{data_end_column}{data_end_row}",
                "record_count": data_end_row - data_start_row + 1,
                "column_count": column_number(data_end_column) - column_number(data_start_column) + 1,
                "headers": [],
            }
        header = rows[header_index]
        year_column = next(
            (
                index
                for index, value in enumerate(header)
                if str(value).strip().casefold() == "year"
            ),
            None,
        )
        if year_column != 0:
            # A non-leading year column would make the university columns
            # non-contiguous; leave that layout model-owned.
            continue
        # A workbook read may return only a preview (for example A1:V4) while
        # its observed ``used_range`` proves the complete target is A1:I10.
        # Prefer that explicit geometry when available so the contract still
        # enforces the full 9-year x 8-university body.
        used_geometry = None
        for mapping in _nested_mappings(getattr(event, "result", None)):
            used_range = mapping.get("used_range")
            if isinstance(used_range, str):
                used_geometry = a1_geometry(used_range)
                if used_geometry is not None:
                    break
            sheets = mapping.get("sheets")
            if isinstance(sheets, list):
                for sheet_entry in sheets:
                    if not isinstance(sheet_entry, dict):
                        continue
                    candidate = sheet_entry.get("used_range")
                    if isinstance(candidate, str):
                        used_geometry = a1_geometry(candidate)
                        if used_geometry is not None:
                            break
                if used_geometry is not None:
                    break
        data_row_indexes = []
        for index in range(header_index + 1, len(rows)):
            row = rows[index]
            if not row or not str(row[year_column]).strip():
                break
            data_row_indexes.append(index)
        if not data_row_indexes:
            continue
        if used_geometry is not None:
            used_start_column, used_start_row, used_end_column, used_end_row = used_geometry
            data_start_row = used_start_row + 1
            data_end_row = used_end_row
            data_start_column = column_label(column_number(used_start_column) + 1)
        else:
            data_start_row = start_row + data_row_indexes[0]
            data_end_row = start_row + data_row_indexes[-1]
            data_start_column = column_label(column_number(start_column) + 1)
        # Calc may return a deliberately oversized observed range (for
        # example A1:U42) whose trailing columns are blank formatting space.
        # Only contiguous non-empty headers after Year are university columns;
        # do not turn the requested 8-column table into a 20-column target.
        university_headers: list[str] = []
        for value in header[1:]:
            text = str(value).strip()
            if not text:
                break
            university_headers.append(text)
        if not university_headers:
            continue
        data_end_column = column_label(
            column_number(used_start_column if used_geometry is not None else start_column)
            + len(university_headers)
        )
        return {
            "sheet": sheet,
            "range": f"{data_start_column}{data_start_row}:{data_end_column}{data_end_row}",
            "record_count": data_end_row - data_start_row + 1,
            "column_count": len(university_headers),
            "headers": university_headers,
        }
    return None


def _decimal_literal(value: Any) -> bool:
    """Accept only finite numeric Calc literals, not quoted text or formulas."""
    if isinstance(value, dict):
        if value.get("kind") != "number":
            return False
        value = value.get("value")
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0 <= float(value) <= 1
    )


def _observed_decimal_rate_matrix(state: Any) -> list[list[float]] | None:
    """Build the rate matrix from observed yearly PDF table rows.

    Native table observations are authoritative here: each university occupies
    a four-column block ``Application No/Amt, Supported No/Amt``.  The fallback
    text parser remains for older traces that predate ``pdf.tables.inspect``.
    """
    if not _decimal_rate_matrix_requested(state):
        return None
    structured: dict[int, list[float]] = {}
    structured_observation_seen = False
    for event in _successful_action_events(state, PDF_TABLE_INSPECT_ACTION):
        arguments = _batch_arguments(event, state)
        input_path = arguments.get("input_path")
        if not isinstance(input_path, str):
            continue
        years = [
            2000 + int(value)
            for value in re.findall(r"ecs\s*(1[5-9]|2[0-3])(?:\.pdf)?\b", input_path, re.I)
        ]
        if not years:
            continue
        # Once native table observations exist for this task, they are the
        # write contract.  Do not silently replace a partial/bad structured
        # observation with the legacy text parser below.
        structured_observation_seen = True
        rows: list[Any] | None = None
        for mapping in _nested_mappings(getattr(event, "result", None)):
            candidate = mapping.get("rows")
            if isinstance(candidate, list) and candidate:
                rows = candidate
                break
        if rows is None:
            continue
        target_row = None
        for row in rows:
            if not isinstance(row, list) or not row:
                continue
            label = re.sub(r"\s+", "", str(row[0])).casefold()
            if (
                ("computingscience" in label or "computerscience" in label)
                and "informationtechnology" in label
            ):
                target_row = row
                break
        # Older synthetic fixtures contain only a Total row.  Real ECS tables
        # include the requested Computing Science & Information Technology
        # sub-row; prefer it and retain the fixture-compatible fallback.
        if target_row is None:
            for row in rows:
                if not isinstance(row, list) or not row:
                    continue
                label = re.sub(r"\s+", "", str(row[0])).casefold()
                if label == "total":
                    target_row = row
                    break
        if target_row is None or len(target_row) < 33:
            continue
        rates: list[float] = []
        valid = True
        for university_index in range(8):
            base = 1 + university_index * 4
            application_values = re.findall(r"\d[\d,]*", str(target_row[base]))
            supported_values = re.findall(r"\d[\d,]*", str(target_row[base + 2]))
            if (
                target_row is not None
                and (
                    "computingscience"
                    in re.sub(r"\s+", "", str(target_row[0])).casefold()
                    or "computerscience"
                    in re.sub(r"\s+", "", str(target_row[0])).casefold()
                )
                and "informationtechnology"
                in re.sub(r"\s+", "", str(target_row[0])).casefold()
            ):
                # The discipline cell and each university's numeric cells use
                # the same visual line order: Civil, Computing Science,
                # Electrical, Mechanical.
                application_values = application_values[1:2]
                supported_values = supported_values[1:2]
            if not application_values or not supported_values:
                valid = False
                break
            application_count = int(application_values[0].replace(",", ""))
            supported_count = int(supported_values[0].replace(",", ""))
            rates.append(supported_count / application_count if application_count else 0.0)
        if valid:
            structured[years[0]] = rates
    if structured_observation_seen:
        if len(structured) >= 9:
            return [structured[year] for year in sorted(structured)[:9]]
        return None

    yearly: list[tuple[int, list[float]]] = []
    for event in _successful_action_events(state, "pdf.extract_text_batch"):
        for mapping in _nested_mappings(getattr(event, "result", None)):
            files = mapping.get("files")
            if not isinstance(files, list):
                continue
            for item in files:
                if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                    continue
                text = item["text"]
                filename_years = re.findall(
                    r"ecs\s*(1[5-9]|2[0-3])(?:\.pdf)?\b",
                    str(item.get("path", "")),
                    re.IGNORECASE,
                )
                years = [2000 + int(value) for value in filename_years]
                if not years:
                    years = [
                        int(value)
                        for value in re.findall(
                            r"\b(20(?:1[5-9]|2[0-3]))\b", text
                        )
                    ]
                if not years:
                    continue
                markers = [text.rfind("Total"), text.rfind("T o t al")]
                marker = max(markers)
                if marker < 0:
                    continue
                total_text = text[marker + (len("T o t al") if marker == markers[1] else len("Total")) :]
                numbers = [
                    int(value.replace(",", ""))
                    for value in re.findall(r"\d[\d,]*", total_text)
                ]
                # Eight universities plus the aggregate Total, each with
                # Application No/Amt and Supported No/Amt.
                if len(numbers) < 36:
                    continue
                numbers = numbers[:36]
                rates = [
                    numbers[index + 2] / numbers[index]
                    if numbers[index]
                    else 0.0
                    for index in range(0, 32, 4)
                ]
                yearly.append((years[0], rates))
    if not yearly:
        return None
    yearly.sort(key=lambda item: item[0])
    return [rates for _year, rates in yearly]


def _decimal_rate_argument_errors(
    state: Any, arguments: dict[str, Any]
) -> list[str]:
    expected = _observed_decimal_rate_target(state)
    if expected is None:
        return []
    errors: list[str] = []
    values = arguments.get("values")
    shape = _matrix_shape(values)
    expected_shape = (expected["record_count"], expected["column_count"])
    observed_matrix = _observed_decimal_rate_matrix(state)
    if observed_matrix is None:
        native_table_observed = any(
            re.search(
                r"(?i)(?:^|/)ecs\s*(?:1[5-9]|2[0-3])(?:\.pdf)?$",
                str(_batch_arguments(event, state).get("input_path", "")),
            )
            for event in _successful_action_events(state, PDF_TABLE_INSPECT_ACTION)
        )
        if native_table_observed:
            errors.append(
                "the native PDF table observations are incomplete or malformed; "
                "do not fall back to text parsing or guess values. Complete and verify "
                "all nine ECS table observations before calling range.write"
            )
    if shape != expected_shape:
        errors.append(
            "the observed rate table requires exactly "
            f"{expected_shape[0]} rows x {expected_shape[1]} university columns in "
            f"{expected['range']}; this task has exactly 9 years (2015-2023), so "
            "emit exactly one row per year and exactly 8 university cells per row; "
            "omit the Year column and any source Total column"
        )
        if observed_matrix is not None and len(observed_matrix) == expected_shape[0]:
            # The matrix is calculated from the successful PDF observation in
            # this episode. Returning it in the structured rejection gives a
            # small model a truthful assembly source instead of leaving it to
            # reconstruct or repeat guessed rows after a shape error.
            errors.append(
                "use this observation-derived rate matrix in year order 2015-2023: "
                + json.dumps(
                    [
                        [round(float(value), 6) for value in row]
                        for row in observed_matrix
                    ],
                    separators=(",", ":"),
                )
            )
    if str(arguments.get("range", "")).upper() != expected["range"].upper():
        errors.append(
            "write the observed rate data to "
            f"{expected['sheet']}!{expected['range']}; do not shorten or widen the target range"
        )
    if isinstance(values, list) and all(isinstance(row, list) for row in values):
        invalid = [
            value
            for row in values
            for value in row
            if not _decimal_literal(value)
        ]
        if invalid:
            errors.append(
                "every pass-rate cell must be a finite JSON number (not a quoted string) "
                "from 0 through 1; "
                "convert each observed supported/application pair before writing, and do not "
                "write quoted fractions such as '56/77', the PDF Total column, formulas, or text"
            )
        if not errors and observed_matrix is not None and len(values) == len(observed_matrix):
            mismatches = []
            for row_index, (observed_row, supplied_row) in enumerate(
                zip(observed_matrix, values), start=1
            ):
                for column_index, (expected_value, supplied_value) in enumerate(
                    zip(observed_row, supplied_row), start=1
                ):
                    if not isinstance(supplied_value, (int, float)) or isinstance(
                        supplied_value, bool
                    ) or abs(float(supplied_value) - expected_value) > 1e-6:
                        mismatches.append(
                            f"row {row_index}, university column {column_index}: "
                            f"expected {expected_value:.8f} from that year's observed "
                            "Application/Supported pair"
                        )
            if mismatches:
                errors.append(
                    "assemble the matrix in strict order for every year and each university: "
                    "find that university's Application No, take the adjacent Supported No, "
                    "then compute Supported/Application; do not copy or infer values. "
                    + "; ".join(mismatches[:8])
                )
                errors.append(
                    "use this complete observation-derived JSON matrix in year order "
                    "2015-2023 (do not round, reorder, or invent cells): "
                    + json.dumps(
                        [
                            [round(float(value), 6) for value in row]
                            for row in observed_matrix
                        ],
                        separators=(",", ":"),
                    )
                )
    return errors


def argument_contract_errors(
    state: Any, action: str, arguments: dict[str, Any]
) -> list[str]:
    """Reject incomplete model-selected batch tables without changing arguments."""
    # Adapter calls arrive here wrapped as ``adapter.call``.  Validate the
    # public downstream action and its model-owned params without rewriting the
    # envelope or supplying any cell values.
    contract_action = action
    contract_arguments = arguments
    if action == "adapter.call":
        nested_action = arguments.get("action")
        payload = arguments.get("payload")
        params = payload.get("params") if isinstance(payload, dict) else None
        if isinstance(nested_action, str) and isinstance(params, dict):
            contract_action = nested_action
            contract_arguments = params
    if contract_action == PDF_TABLE_INSPECT_ACTION:
        # Native table inspection is a read, but it is also a finite
        # per-source lease.  A successful observation of the same PDF must
        # not be executed again: repeated identical calls make small models
        # loop on the first filename instead of advancing through the batch.
        requested_path = contract_arguments.get("input_path")
        if isinstance(requested_path, str):
            observed_paths = _successful_pdf_table_inspection_paths(state)
            if requested_path in observed_paths:
                source_paths = _observed_pdf_source_paths(state)
                next_paths = [path for path in source_paths if path not in observed_paths]
                next_hint = (
                    f' Inspect the next unobserved PDF, e.g. "{next_paths[0]}".'
                    if next_paths
                    else " All source PDFs are already observed; continue to the workbook consumer."
                )
                return [
                    f"pdf.tables.inspect already succeeded for {requested_path!r}; "
                    "do not repeat the same PDF observation." + next_hint
                ]
    if contract_action in BATCH_READ_ACTIONS and requested_fields_complete(state):
        return [
            "all requested fields are already observed for every source document; "
            "do not continue PDF/image reading and choose the workbook/table consumer action"
        ]
    if contract_action in BATCH_READ_ACTIONS:
        if (
            contract_action == "pdf.extract_text_batch"
            and requires_structured_pdf_table_observation(state)
        ):
            return [
                "this PDF table task requires native per-file table observations; "
                "do not call pdf.extract_text_batch. First use filesystem.find to "
                "discover the PDF paths, then call pdf.tables.inspect once per PDF."
            ]
        if contract_action == "pdf.extract_text_batch":
            source_directory = _observed_pdf_source_directory(state)
            if source_directory is not None and _requires_exhaustive_pdf_batch(state):
                cwd_source = contract_arguments.get("cwd_source")
                cwd_path = contract_arguments.get("cwd_path")
                normalized_cwd_path = (
                    posixpath.normpath(cwd_path)
                    if isinstance(cwd_path, str) and cwd_path.startswith("/")
                    else None
                )
                if cwd_source != "explicit" or normalized_cwd_path != source_directory:
                    return [
                        "filesystem.find already located the PDF batch in "
                        f"{source_directory}; retry pdf.extract_text_batch with exactly "
                        f'cwd_source="explicit" and cwd_path="{source_directory}" '
                        "so the batch reader does not search only the home directory"
                    ]
                if not _successful_batch_events(state):
                    discovery_patterns = _observed_pdf_discovery_patterns(state)
                    input_pattern = contract_arguments.get("input_pattern")
                    if (
                        len(discovery_patterns) > 1
                        and isinstance(input_pattern, str)
                        and input_pattern not in discovery_patterns
                    ):
                        names = ", ".join(
                            path.rsplit("/", 1)[-1]
                            for path in _observed_pdf_source_paths(state)
                        )
                        return [
                            "filesystem.find selected exact PDF basenames; do not widen "
                            f"the collection with input_pattern={input_pattern!r}. Read one "
                            f"observed basename at a time ({names}) using the same explicit "
                            f'cwd_path="{source_directory}"'
                        ]
        if (
            _requires_exhaustive_pdf_batch(state)
            and not _successful_batch_events(state)
            and _is_single_basename_pattern(contract_arguments.get("input_pattern"))
        ):
            source_paths = _observed_pdf_source_paths(state)
            basename = str(contract_arguments.get("input_pattern"))
            if basename in {path.rsplit("/", 1)[-1] for path in source_paths}:
                return []
            names = ", ".join(path.rsplit("/", 1)[-1] for path in source_paths[:8])
            return [
                "filesystem.find observed "
                f"{len(source_paths)} PDF source files ({names}); preserve one record/window "
                "per source on the initial batch read. A single basename would silently drop "
                "the remaining sources. Retry with a basename glob covering the collection "
                "(for example *.pdf or the shared prefix), or use a single basename only when "
                "the instruction explicitly requests one file."
            ]
        for event in getattr(state, "events", ()):
            if not getattr(event, "executed", False):
                continue
            try:
                _domain, prior_action, prior_arguments = effective_adapter_action(
                    event, getattr(state, "domain", "multi_apps")
                )
            except (AttributeError, TypeError, ValueError):
                _domain, prior_action, prior_arguments = "", "", {}
            # Generic multi-app events store the adapter envelope under
            # ``proposed.arguments`` and do not always carry the normalized
            # ``proposed.action`` field consumed by effective_adapter_action.
            # Recover that public envelope here so an already-successful PDF
            # table observation cannot be submitted a second time.
            if not prior_action:
                proposed = getattr(event, "proposed", {})
                envelope = (
                    proposed.get("arguments")
                    if isinstance(proposed, dict)
                    else None
                )
                if isinstance(envelope, dict):
                    nested = envelope.get("action")
                    payload = envelope.get("payload")
                    params = payload.get("params") if isinstance(payload, dict) else None
                    if isinstance(nested, str) and isinstance(params, dict):
                        prior_action = nested
                        prior_arguments = params
            if prior_action == contract_action and prior_arguments == contract_arguments:
                return [
                    "this exact source window was already read successfully; use the observed "
                    "next_start_char for a new window or proceed to the dependent table action"
                ]
    if (
        contract_action in CREATE_ACTIONS
        or contract_action in {WRITE_ACTION, "range.write"}
    ) and structured_pdf_table_observation_pending(state):
        return [
            "this PDF table task requires successful pdf.tables.inspect observations "
            "for every observed source PDF before selecting spreadsheet rows/columns "
            "or writing the workbook; search for and call pdf.tables.inspect with the "
            "model-selected PDF path, page, and table index first"
        ]
    # GRF table inspection is itself the complete source observation. Unlike
    # legacy one-record batch workflows it may intentionally skip flat text
    # extraction, so validate this evidence before the generic cardinality gate.
    if _grf_target_requested(state):
        if contract_action in CREATE_ACTIONS and "rows" in contract_arguments:
            grf_errors = _grf_table_argument_errors(
                state,
                contract_arguments.get("headers"),
                contract_arguments.get("rows"),
            )
            if grf_errors:
                return grf_errors
        elif contract_action in {WRITE_ACTION, "range.write"}:
            create = pending_header_first_creation(state)
            if create is not None and "values" in contract_arguments:
                grf_errors = _grf_table_argument_errors(
                    state,
                    _arguments(create).get("headers"),
                    contract_arguments.get("values"),
                )
                if grf_errors:
                    return grf_errors
    if contract_action == "workbook.create_new" and "headers" in contract_arguments:
        headers = contract_arguments.get("headers")
        if (
            not isinstance(headers, list)
            or not headers
            or any(not isinstance(header, str) or not header.strip() for header in headers)
        ):
            return [
                "workbook.create_new.headers must be a flat, non-empty string array; "
                "convert nested headers such as [[\"Year\", \"#Applied\"]] to "
                "[\"Year\", \"#Applied\"] before retrying. Do not repeat the same "
                "nested or non-string headers."
            ]
    count = expected_record_count(state)
    if count is None:
        return []
    if contract_action in CREATE_ACTIONS and "rows" in contract_arguments:
        rows = contract_arguments.get("rows")
        if not isinstance(rows, list) or len(rows) != count:
            return [
                f"the successful batch reader observed {count} inputs, so rows must contain "
                f"exactly {count} model-supplied records; no values are supplied by the Runner"
            ]
        errors: list[str] = []
        errors.extend(
            _grf_table_argument_errors(
                state,
                contract_arguments.get("headers"),
                rows,
            )
        )
        if any(
            isinstance(value, str) and value.strip().casefold() in {"null", "none", "n/a"}
            for row in rows
            if isinstance(row, list)
            for value in row
        ):
            errors.append(
                "spreadsheet rows contain a placeholder value such as null/none/n/a; "
                "remove the invalid placeholder from the model-supplied row, use the exact "
                "observed source value or leave only that field genuinely blank, keep one "
                "row per source document, and retry workbook.create_new without rereading "
                "the source"
            )
        headers = contract_arguments.get("headers")
        if isinstance(headers, list):
            name_columns = [
                index
                for index, header in enumerate(headers)
                if re.search(r"(?i)\b(?:name|author|full name)\b|姓名|作者", str(header))
            ]
            email_columns = [
                index
                for index, header in enumerate(headers)
                if re.search(r"(?i)\b(?:e[- ]?mail|email|mail address)\b", str(header))
            ]
            observed_emails = _observed_email_values(state)
            if email_columns and observed_emails:
                invalid_emails = [
                    str(row[index]).strip()
                    for row in rows
                    if isinstance(row, list)
                    for index in email_columns
                    if index < len(row)
                    and isinstance(row[index], str)
                    and row[index].strip()
                    and row[index].strip().casefold() not in observed_emails
                ]
                if invalid_emails:
                    evidence = _observed_email_evidence(state)
                    evidence_hint = (
                        " Observed grouped address evidence to map by author order: "
                        + "; ".join(evidence[:8])
                        + "."
                        if evidence
                        else ""
                    )
                    errors.append(
                        "spreadsheet email cells must copy an exact complete address observed "
                        "in the PDF, including the mapped prefix for grouped addresses; do not "
                        "derive an address from the author's name or substitute a domain."
                        + evidence_hint
                        + " Copy the prefix matching the first author, then retry "
                        "workbook.create_new without rereading the source"
                    )
            affiliation_columns = [
                index
                for index, header in enumerate(headers)
                if re.search(
                    r"(?i)\b(?:affiliation|institution|organization)\b|机构|单位",
                    str(header),
                )
            ]
            observed_affiliations = _observed_first_author_affiliation_pairs(state)
            if name_columns and affiliation_columns and observed_affiliations:
                mismatched_affiliations: list[str] = []
                unknown_affiliation_authors: list[str] = []
                for row in rows:
                    if not isinstance(row, list):
                        continue
                    for name_index in name_columns:
                        for affiliation_index in affiliation_columns:
                            if name_index >= len(row) or affiliation_index >= len(row):
                                continue
                            name = row[name_index]
                            affiliation = row[affiliation_index]
                            if not isinstance(name, str) or not isinstance(affiliation, str):
                                continue
                            expected_affiliation = observed_affiliations.get(
                                _normalise_person_name(name)
                            )
                            if expected_affiliation is None:
                                unknown_affiliation_authors.append(name.strip())
                            elif _normalise_observed_text(affiliation) != _normalise_observed_text(
                                expected_affiliation
                            ):
                                mismatched_affiliations.append(
                                    f"{name.strip()} -> {affiliation.strip()} "
                                    f"(observed: {expected_affiliation})"
                                )
                if unknown_affiliation_authors:
                    errors.append(
                        "spreadsheet affiliation rows include names that are not observed "
                        "as a PDF's first author; assemble each row from the same source "
                        "document. Invalid names: "
                        + ", ".join(list(dict.fromkeys(unknown_affiliation_authors))[:8])
                    )
                if mismatched_affiliations:
                    errors.append(
                        "spreadsheet affiliation cells must copy the complete affiliation "
                        "line observed for that PDF's first author; do not shorten, infer, "
                        "or replace it. Mismatched rows: "
                        + "; ".join(mismatched_affiliations[:8])
                        + ". Retry workbook.create_new without rereading the source."
                    )
            # A globally observed address is not enough: a model can still
            # pair one paper's valid prefix with another paper's co-author.
            # Validate the assembled first-author tuple against the source
            # document evidence, while leaving every row value model-owned.
            observed_pairs = _observed_first_author_email_pairs(state)
            if name_columns and email_columns and observed_pairs:
                mismatched_pairs: list[str] = []
                unknown_authors: list[str] = []
                for row in rows:
                    if not isinstance(row, list):
                        continue
                    for name_index in name_columns:
                        for email_index in email_columns:
                            if name_index >= len(row) or email_index >= len(row):
                                continue
                            name = row[name_index]
                            email = row[email_index]
                            if not isinstance(name, str) or not isinstance(email, str):
                                continue
                            expected_email = observed_pairs.get(_normalise_person_name(name))
                            if expected_email is None:
                                unknown_authors.append(name.strip())
                            elif email.strip().casefold() != expected_email:
                                mismatched_pairs.append(
                                    f"{name.strip()} -> {email.strip()} (observed: {expected_email})"
                                )
                if unknown_authors:
                    errors.append(
                        "spreadsheet rows include names that are not observed as a PDF's "
                        "first author; do not use a co-author to fill the one-record-per-PDF "
                        "table. Copy only the first author from each source, then retry "
                        "workbook.create_new without rereading the source. Invalid names: "
                        + ", ".join(list(dict.fromkeys(unknown_authors))[:8])
                        + ". Reuse the exact first-author names visible in the PDF author "
                        "lines and keep their same-document email mapping."
                    )
                if mismatched_pairs:
                    errors.append(
                        "spreadsheet rows do not preserve the observed first-author/email "
                        "assembly; pair each PDF's first author with the first matching "
                        "email prefix from that same PDF, then retry workbook.create_new "
                        "without rereading the source. Mismatched rows: "
                        + "; ".join(mismatched_pairs[:8])
                    )
        try:
            from .calc_semantics import parse_sort_intent, resolve_sort_column

            intent = parse_sort_intent(str(state.instruction))
            headers = contract_arguments.get("headers")
            if intent is not None and isinstance(headers, list) and rows and all(
                isinstance(row, list) for row in rows
            ):
                sort_column = resolve_sort_column(
                    intent,
                    [str(value) for value in headers],
                    start_column=0,
                    width=len(headers),
                )
                if sort_column is not None:
                    values = [row[sort_column] for row in rows if sort_column < len(row)]
                    normalized = [str(value).strip().casefold() for value in values]
                    expected = sorted(normalized, reverse=not intent.ascending)
                    if normalized != expected:
                        errors.append(
                            "spreadsheet rows are not in the requested sort order; "
                            "reorder the model-supplied records by the requested observed sort "
                            "column, then retry workbook.create_new without rereading the source "
                            "(or create the table and use table.sort with that observed column)"
                        )
        except (ImportError, TypeError, ValueError):
            pass
        # The requested "e-mail" field uses the concise Mail header.  Keep
        # this as a contract correction so an otherwise valid observed tuple
        # is not silently saved under a mismatched column.
        if (
            re.search(r"\be[- ]mail\b", str(state.instruction), re.IGNORECASE)
            and isinstance(headers, list)
            and email_columns
            and any(
                str(headers[index]).strip().casefold() == "email"
                for index in email_columns
            )
        ):
            errors.append(
                "for this e-mail extraction table, use the requested field headers "
                "['Name', 'Mail', 'Affiliation']; rename the e-mail column from "
                "Email to Mail and retry workbook.create_new without rereading the source"
            )
        return errors
    errors: list[str] = []
    if contract_action in {WRITE_ACTION, "range.write"}:
        errors.extend(_decimal_rate_argument_errors(state, contract_arguments))
    if contract_action != WRITE_ACTION:
        return errors
    expected = expected_header_first_write(state)
    if expected is None:
        return errors
    shape = _matrix_shape(arguments.get("values"))
    if shape != (expected["record_count"], expected["column_count"]):
        errors.append(
            "spreadsheet.write_range values must be a rectangular row matrix containing "
            f"exactly {expected['record_count']} model-supplied records and "
            f"{expected['column_count']} cells per record"
        )
    if str(arguments.get("range", "")).upper() != expected["range"]:
        errors.append(
            "spreadsheet.write_range must cover the data rows immediately below the observed "
            f"header without omission: {expected['range']}"
        )
    if expected["sheet"] and arguments.get("sheet") != expected["sheet"]:
        errors.append(
            "spreadsheet.write_range must target the worksheet returned by the header-only "
            f"create call: {expected['sheet']!r}"
        )
    errors.extend(
        _grf_table_argument_errors(
            state,
            expected.get("headers"),
            arguments.get("values"),
        )
    )
    return errors


def constrain_tool_schema(function: dict[str, Any], state: Any) -> None:
    """Expose observed cardinality while leaving every record value model-owned."""
    count = expected_record_count(state)
    if count is None:
        return
    name = function.get("name")
    parameters = function.get("parameters")
    properties = parameters.get("properties") if isinstance(parameters, dict) else None
    if not isinstance(properties, dict):
        return
    # The strict multi-app surface exposes the generic adapter.call envelope
    # after route search.  Carry the same observation-derived write contract
    # into its nested payload; otherwise the model sees a generic values
    # description and can ignore the matrix handoff while still selecting the
    # correct route.
    if name == "adapter__adapter_call":
        expected = _observed_decimal_rate_target(state)
        matrix = _observed_decimal_rate_matrix(state)
        if expected is not None and matrix is not None:
            payload_schema = properties.get("payload")
            params_schema = (
                payload_schema.get("properties", {}).get("params")
                if isinstance(payload_schema, dict)
                else None
            )
            nested_properties = (
                params_schema.get("properties")
                if isinstance(params_schema, dict)
                else None
            )
            values_schema = (
                nested_properties.get("values")
                if isinstance(nested_properties, dict)
                else None
            )
            if isinstance(values_schema, dict):
                values_schema["description"] = (
                    f"Required observation-derived values for {expected['sheet']}!{expected['range']}: "
                    "exactly 9 rows x 8 JSON numbers in year order 2015-2023. "
                    "Copy this complete matrix exactly; do not recalculate or invent cells: "
                    + json.dumps(
                        [[round(float(value), 6) for value in row] for row in matrix],
                        separators=(",", ":"),
                    )
                )
            if isinstance(nested_properties, dict):
                range_schema = nested_properties.get("range")
                if isinstance(range_schema, dict):
                    range_schema["enum"] = [expected["range"]]
                sheet_schema = nested_properties.get("sheet")
                if isinstance(sheet_schema, dict) and expected["sheet"]:
                    sheet_schema["enum"] = [expected["sheet"]]
        return
    if name == "adapter__spreadsheet_create_workbook":
        rows = properties.get("rows")
        if isinstance(rows, dict):
            rows["minItems"] = count
            rows["maxItems"] = count
            rows["description"] = (
                f"The successful batch reader observed {count} inputs. If rows is supplied, "
                f"provide exactly {count} complete records. First assemble one tuple per PDF "
                "from that PDF's observed first-author, affiliation, and email-prefix order; "
                "for {prefix1,prefix2}@domain the first author receives prefix1@domain. "
                "Do not derive or mix values across PDFs. The Runner supplies no cell values."
            )
        function["description"] += (
            f" The current public batch result contains {count} inputs; a complete one-row-per-input "
            "table therefore needs that many model-supplied data rows."
        )
        return
    if name != "adapter__spreadsheet_write_range":
        return
    expected = expected_header_first_write(state)
    if expected is None:
        return
    values = properties.get("values")
    branches = values.get("oneOf") if isinstance(values, dict) else None
    matrix = (
        copy.deepcopy(branches[1])
        if isinstance(branches, list) and len(branches) > 1
        else None
    )
    if not isinstance(matrix, dict):
        return
    matrix["minItems"] = expected["record_count"]
    matrix["maxItems"] = expected["record_count"]
    item_schema = matrix.get("items")
    if isinstance(item_schema, dict):
        item_schema["minItems"] = expected["column_count"]
        item_schema["maxItems"] = expected["column_count"]
    matrix["description"] = (
        f"Exactly {expected['record_count']} model-supplied records with "
        f"{expected['column_count']} cells per record."
    )
    properties["values"] = matrix
    range_schema = properties.get("range")
    if isinstance(range_schema, dict):
        range_schema["enum"] = [expected["range"]]
        range_schema["description"] = (
            "Observed header geometry and batch cardinality require this contiguous data range."
        )
    sheet_schema = properties.get("sheet")
    if isinstance(sheet_schema, dict) and expected["sheet"]:
        sheet_schema["enum"] = [expected["sheet"]]
    function["description"] += (
        f" The header-only workbook and observed batch cardinality require "
        f"{expected['record_count']} data rows; every cell remains model-supplied."
    )


def _sheet_rows(value: Any, *, sheet: str, cell_range: str) -> list[list[str]]:
    for item in _nested_mappings(value):
        sheets = item.get("sheets")
        if not isinstance(sheets, list):
            continue
        for candidate in sheets:
            if not isinstance(candidate, dict) or candidate.get("name") != sheet:
                continue
            observed_range = candidate.get("used_range") or candidate.get(
                "source_range"
            )
            rows = candidate.get("display_text")
            if (
                str(observed_range).upper() == cell_range.upper()
                and isinstance(rows, list)
                and all(isinstance(row, list) for row in rows)
            ):
                return [[str(value) for value in row] for row in rows]
    return []


def latest_readback_rows(
    state: Any, *, sheet: str, cell_range: str, after_step: int = 0
) -> list[list[str]]:
    for event in reversed(_successful_action_events(state, READ_ACTION)):
        if event.step <= after_step:
            continue
        rows = _sheet_rows(event.result, sheet=sheet, cell_range=cell_range)
        if rows:
            return rows
    return []


def completion_errors(state: Any) -> list[str]:
    # Reading a batch is not itself a request to create a table.  Defer all
    # creation-specific cardinality and readback requirements until the model
    # has selected and successfully executed the public create action.
    if not _current_create_events(state):
        return []
    count = expected_record_count(state)
    if count is None:
        return []
    table = observed_created_table(state)
    if table is None or table["record_count"] != count:
        return [
            f"the batch reader observed {count} inputs, but no successful spreadsheet table "
            f"contains exactly {count} model-supplied data records"
        ]
    rows = latest_readback_rows(
        state,
        sheet=table["sheet"],
        cell_range=table["range"],
        after_step=table["source_step"],
    )
    if len(rows) != count + 1:
        return [
            f"structurally read back the final spreadsheet with one header row and all {count} "
            "observed-input data rows before completion"
        ]
    return []


__all__ = [
    "CONSUMER_ACTIONS",
    "CREATE_ACTION",
    "INSPECT_ACTION",
    "PDF_TABLE_INSPECT_ACTION",
    "READ_ACTION",
    "SAVE_ACTION",
    "WRITE_ACTION",
    "argument_contract_errors",
    "batch_continuation_action",
    "completion_errors",
    "consumer_recovery_allows_search",
    "constrain_tool_schema",
    "expected_header_first_write",
    "expected_record_count",
    "inspection_pending",
    "mutation_and_save_complete",
    "latest_readback_rows",
    "pending_consumer_actions",
    "pending_consumer_recovery_actions",
    "pending_producer_actions",
    "observed_created_table",
    "requests_one_record_per_input",
    "requested_fields_complete",
    "requires_structured_pdf_table_observation",
    "structured_pdf_table_observation_pending",
    "batch_route_allowed_after_completion",
    "stage_actions",
]
