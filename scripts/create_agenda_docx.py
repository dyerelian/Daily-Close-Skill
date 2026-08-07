#!/usr/bin/env python3
"""Small, self-contained OOXML agenda renderer used by close-day exports."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


def text(value: object) -> str:
    return "" if value is None else str(value)


def run_xml(value: object, bold: bool = False, italic: bool = False) -> str:
    properties = []
    if bold:
        properties.append("<w:b/>")
    if italic:
        properties.append("<w:i/>")
    rpr = f"<w:rPr>{''.join(properties)}</w:rPr>" if properties else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text(value))}</w:t></w:r>'


def paragraph_xml(runs: list[str], style: str | None = None, bullet: bool = False) -> str:
    properties = []
    if style:
        properties.append(f'<w:pStyle w:val="{escape(style)}"/>')
    if bullet:
        properties.append('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
    ppr = f"<w:pPr>{''.join(properties)}</w:pPr>" if properties else ""
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def simple_paragraph(value: object, style: str | None = None, bullet: bool = False) -> str:
    return paragraph_xml([run_xml(value)], style=style, bullet=bullet)


def _bullet_values(parts: list[str], heading: str, values: object) -> None:
    rendered = [text(value).strip() for value in (values or []) if text(value).strip()]
    if not rendered:
        return
    parts.append(simple_paragraph(heading, style="Heading2"))
    parts.extend(simple_paragraph(value, bullet=True) for value in rendered)


def document_body(agenda: dict) -> str:
    """Render an agenda body suitable for a standalone or combined document."""
    parts = [simple_paragraph(agenda.get("title") or "Meeting Agenda", style="Title")]
    subtitle = text(agenda.get("subtitle")).strip()
    if subtitle:
        parts.append(simple_paragraph(subtitle, style="Subtitle"))

    recap = agenda.get("last_meeting_recap") or {}
    if recap:
        parts.append(simple_paragraph("Last meeting recap", style="Heading1"))
        parts.append(simple_paragraph(recap.get("summary") or "No prior meeting found."))
        _bullet_values(parts, "Open follow-ups", recap.get("follow_ups"))
        _bullet_values(parts, "Decisions", recap.get("decisions"))
        _bullet_values(parts, "Suggested talking points", recap.get("talking_points"))

    _bullet_values(parts, "Send ahead", agenda.get("send_ahead_bullets"))
    _bullet_values(parts, "Context reviewed", agenda.get("context_reviewed"))
    for section in agenda.get("sections") or []:
        if not isinstance(section, dict):
            continue
        heading = text(section.get("heading")).strip()
        if heading:
            parts.append(simple_paragraph(heading, style="Heading1"))
        for item in section.get("items") or []:
            if isinstance(item, dict):
                label = text(item.get("label")).strip()
                body = text(item.get("body") or item.get("text")).strip()
                if label:
                    parts.append(paragraph_xml([run_xml(f"{label}: ", bold=True), run_xml(body)]))
                elif body:
                    parts.append(simple_paragraph(body, bullet=True))
            elif text(item).strip():
                parts.append(simple_paragraph(item, bullet=True))
    _bullet_values(parts, "Agenda", agenda.get("items"))
    return "\n".join(parts)


def content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
</Types>
"""


def root_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""


def document_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
</Relationships>
"""


def styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:rPr><w:i/><w:color w:val="666666"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
</w:styles>
"""


def numbering_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="&#8226;"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>
"""


def standalone_document_xml(agenda: dict) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{document_body(agenda)}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body>
</w:document>
"""


def create_docx(agenda: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types_xml())
        docx.writestr("_rels/.rels", root_rels_xml())
        docx.writestr("word/_rels/document.xml.rels", document_rels_xml())
        docx.writestr("word/document.xml", standalone_document_xml(agenda))
        docx.writestr("word/styles.xml", styles_xml())
        docx.writestr("word/numbering.xml", numbering_xml())


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a standalone agenda DOCX.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with Path(args.input).expanduser().open("r", encoding="utf-8-sig") as handle:
        agenda = json.load(handle)
    create_docx(agenda, Path(args.output).expanduser())
    print(f"Wrote {Path(args.output).expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
