from __future__ import annotations

from types import SimpleNamespace

import jsonschema
import pytest

from integrations.lite_agent.tool_catalog import build_tools
from writer_adapter import uno_worker
from writer_adapter.errors import AdapterError
from writer_adapter.schema import validate_action_params
from writer_adapter.tool_manifest import STRICT_ACTION_PARAM_SCHEMAS


ACTION = "document.add_page_numbers"


def enumeration(values):
    remaining = list(values)
    return SimpleNamespace(
        hasMoreElements=lambda: bool(remaining),
        nextElement=lambda: remaining.pop(0),
    )


class Field:
    def __init__(self, *, page_number=True, offset=0, numbering_type=4):
        self.page_number = page_number
        self.Offset = offset
        self.NumberingType = numbering_type
        self.SubType = SimpleNamespace(value="CURRENT")

    def supportsService(self, name):
        return self.page_number and name == "com.sun.star.text.TextField.PageNumber"


class Paragraph:
    def __init__(self, literal="", *, alignment=0, fields=()):
        self.literal = literal
        self.ParaAdjust = alignment
        self.fields = list(fields)

    @property
    def String(self):
        return self.literal + "".join("1" for _field in self.fields)

    def createEnumeration(self):
        portions = []
        if self.literal:
            portions.append(SimpleNamespace(String=self.literal))
        portions.extend(SimpleNamespace(TextField=field) for field in self.fields)
        return enumeration(portions)


class Cursor:
    def __init__(self, footer):
        self.footer = footer
        self.paragraph = footer.paragraphs[-1]

    @property
    def ParaAdjust(self):
        return self.paragraph.ParaAdjust

    @ParaAdjust.setter
    def ParaAdjust(self, value):
        self.paragraph.ParaAdjust = value


class Footer:
    def __init__(self, paragraphs):
        self.paragraphs = list(paragraphs)

    @property
    def String(self):
        return "\n".join(paragraph.String for paragraph in self.paragraphs)

    def getEnd(self):
        return self

    def createTextCursorByRange(self, _range):
        return Cursor(self)

    def insertControlCharacter(self, _cursor, control, absorb):
        assert control == 0
        assert absorb is False
        self.paragraphs.append(Paragraph())

    def insertTextContent(self, cursor, field, absorb):
        assert absorb is False
        cursor.paragraph.fields.append(field)


class Document:
    def __init__(self, styles):
        self.styles = styles
        self.refresh_count = 0
        collection = SimpleNamespace(
            getElementNames=lambda: tuple(styles),
            getByName=styles.__getitem__,
        )
        self.StyleFamilies = SimpleNamespace(getByName=lambda _name: collection)

    def createInstance(self, service):
        assert service == "com.sun.star.text.TextField.PageNumber"
        return Field()

    def getTextFields(self):
        return SimpleNamespace(refresh=self._refresh)

    def _refresh(self):
        self.refresh_count += 1


def page_style(footer, *, in_use=True):
    return SimpleNamespace(
        IsPhysical=True,
        isInUse=lambda: in_use,
        FooterIsOn=True,
        FooterIsShared=True,
        FirstIsShared=True,
        FooterText=footer,
    )


@pytest.fixture(autouse=True)
def fake_paragraphs(monkeypatch):
    monkeypatch.setattr(uno_worker, "_paragraphs", lambda text: list(text.paragraphs))


def test_page_number_contract_is_narrow_and_model_visible():
    exposed = build_tools(
        "libreoffice_writer",
        [ACTION],
        include_gui=False,
        include_control_tools=False,
        strict_generic=True,
    )[0]["function"]

    assert (
        exposed["parameters"]["properties"]
        == (STRICT_ACTION_PARAM_SCHEMAS[ACTION]["properties"])
    )
    assert exposed["parameters"]["required"] == ["position"]
    assert exposed["parameters"]["additionalProperties"] is False
    assert "preserved" in exposed["description"]

    params = {"position": "bottom_left"}
    jsonschema.validate(params, exposed["parameters"])
    validate_action_params(ACTION, params)


@pytest.mark.parametrize(
    "params",
    [{}, {"position": "top_left"}, {"position": "bottom_left", "clear_footer": True}],
)
def test_page_number_contract_rejects_missing_unsupported_or_destructive_params(params):
    schema = build_tools(
        "libreoffice_writer",
        [ACTION],
        include_gui=False,
        include_control_tools=False,
        strict_generic=True,
    )[0]["function"]["parameters"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            params,
            schema,
        )
    with pytest.raises(AdapterError):
        validate_action_params(ACTION, params)


def test_page_number_creation_preserves_existing_footer_content():
    footer = Footer([Paragraph("Confidential report")])
    unused_footer = Footer([Paragraph("Unused template")])
    doc = Document(
        {
            "Body": page_style(footer),
            "Unused": page_style(unused_footer, in_use=False),
        }
    )

    result = uno_worker._add_page_numbers(
        SimpleNamespace(doc=doc), {"position": "bottom_left"}
    )

    assert [paragraph.literal for paragraph in footer.paragraphs] == [
        "Confidential report",
        "",
    ]
    assert footer.paragraphs[0].fields == []
    assert len(footer.paragraphs[1].fields) == 1
    assert footer.paragraphs[1].ParaAdjust == 0
    assert [paragraph.literal for paragraph in unused_footer.paragraphs] == [
        "Unused template"
    ]
    assert result["targets"] == [
        {
            "page_style": "Body",
            "variant": "shared",
            "operation": "created",
            "field_count": 1,
        }
    ]
    assert doc.refresh_count == 1


def test_existing_page_number_is_updated_without_duplicate_or_text_loss():
    existing = Field(offset=7, numbering_type=99)
    footer = Footer([Paragraph("Page ", alignment=3, fields=[existing])])
    doc = Document({"Body": page_style(footer)})

    result = uno_worker._add_page_numbers(
        SimpleNamespace(doc=doc), {"position": "bottom_right"}
    )

    assert len(footer.paragraphs) == 1
    assert footer.paragraphs[0].literal == "Page "
    assert footer.paragraphs[0].fields == [existing]
    assert footer.paragraphs[0].ParaAdjust == 1
    assert existing.Offset == 0
    assert existing.NumberingType == 4
    assert result["targets"][0]["operation"] == "updated"


def test_default_verification_fails_when_native_page_number_readback_is_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        uno_worker,
        "_footer_summary",
        lambda _doc: [
            {
                "page_style": "Body",
                "variant": "shared",
                "enabled": True,
                "page_number_fields": [],
            }
        ],
    )
    monkeypatch.setattr(
        uno_worker,
        "_saved_file_state",
        lambda _path: {"exists": True, "valid": True},
    )
    result = {
        "position": "bottom_left",
        "targets": [
            {
                "page_style": "Body",
                "variant": "shared",
                "operation": "created",
                "field_count": 1,
            }
        ],
    }

    verification = uno_worker._implicit_action_verification(
        ACTION, SimpleNamespace(doc=object(), path="/tmp/document.docx"), result
    )

    assert verification["passed"] is False
    assert verification["checks"] == [
        {
            "type": "page_numbers",
            "page_style": "Body",
            "variant": "shared",
            "passed": False,
        },
        {"type": "file_saved", "passed": True},
    ]
