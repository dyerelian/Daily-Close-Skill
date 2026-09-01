#!/usr/bin/env python3
"""Render a combined "Daily Plan" Word document from structured JSON.

The Daily Plan is the forward-looking output of the `close-day` skill. Its layout,
top to bottom, is: title/date -> yesterday's wins -> today's improvements ->
summary -> meeting insights -> full GTD link -> MIT ("The Frog") -> Daily Big 3
-> top action items -> other action items -> meeting schedule.

This script loads the bundled agenda renderer only for its safe OpenXML text,
paragraph, and package helpers. Standalone agenda exports remain separate files.
Standard library only.

Example:
    python create_daily_plan_docx.py --input plan.json --output "Daily Plan 2026-06-27.docx"
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import zipfile
from pathlib import Path


def default_agenda_script() -> Path:
    configured = os.environ.get("CLOSE_DAY_AGENDA_SCRIPT")
    if configured:
        return Path(configured)
    candidates = [
        Path(__file__).with_name("create_agenda_docx.py"),
        Path.home() / ".codex" / "skills" / "agenda-creator" / "scripts" / "create_agenda_docx.py",
        Path.home() / ".claude" / "skills" / "agenda-creator" / "scripts" / "create_agenda_docx.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


AGENDA_SCRIPT = default_agenda_script()


def load_agenda_module():
    """Load create_agenda_docx.py as a module so its helpers can be reused."""
    if not AGENDA_SCRIPT.exists():
        raise FileNotFoundError(f"agenda-creator script not found: {AGENDA_SCRIPT}")
    spec = importlib.util.spec_from_file_location("agenda_creator", AGENDA_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # safe: the module guards main() behind __main__
    return module


ac = None


def agenda():
    global ac
    if ac is None:
        ac = load_agenda_module()
    return ac


EXAMPLE_DATA = {
    "date": "2026-06-27",
    "quote": {
        "text": "Either you run the day or the day runs you.",
        "author": "Jim Rohn",
    },
    "summary": "Light meeting load; protect the morning for the customer follow-up write-up.",
    "meeting_insights": [
        "The customer wants a concrete implementation sequence before the next sync.",
    ],
    "gtd_link": {
        "label": "Open full GTD list",
        "url": "https://docs.google.com/spreadsheets/d/example/edit",
    },
    "takeaways": {
        "source_day": "2026-06-26",
        "well": [
            "Closed an open decision with a clear owner.",
            "Protected the highest-leverage work block.",
        ],
        "improve": [
            "Send meeting pre-reads one working day earlier.",
        ],
    },
    "mit": "Draft the customer follow-up one-pager (hardest, highest leverage).",
    "daily_big_3": [
        "Customer follow-up one-pager drafted and shared for review",
        "Roadmap input sent to the team lead",
        "Inbox back to zero",
    ],
    "top_actions": [
        {
            "text": "Send out tomorrow's agendas & pre-reads (24h ahead)",
            "sub_bullets": [
                "1:1 with team lead",
                "Team backlog refinement",
            ],
        },
        "A-012 Draft customer follow-up one-pager",
        "A-031 Send roadmap input to the team lead",
        "A-044 Review vendor SOW",
    ],
    "other_actions": [
        "A-051 Book travel for the offsite",
        "A-052 Reply to finance on the PO",
    ],
    "meetings": [
        {"start": "2026-06-27T09:30", "subject": "Project Prioritization Weekly Update"},
        {"start": "2026-06-27T10:00", "subject": "1:1 with team lead", "location": "Conference Room"},
        {"start": "2026-06-27T14:00", "subject": "Team backlog refinement"},
    ],
    "agendas": [
        {
            "title": "1:1 with team lead - 2026-06-27",
            "subtitle": "Prepared agenda",
            "send_ahead_bullets": [
                "Align on top priorities for this week",
                "Review prior commitments and next steps",
            ],
            "context_reviewed": ["Prior 1:1 notes", "Granola meeting notes"],
            "sections": [
                {
                    "heading": "1. Priorities",
                    "items": [
                        {"label": "My focus", "body": "Customer follow-up one-pager and roadmap input."},
                        {"label": "Manager's focus", "body": "Ask for their top three."},
                    ],
                }
            ],
        }
    ],
}


def page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def quote_paragraph(quote: object) -> str | None:
    ac = agenda()
    if isinstance(quote, str):
        quote = {"text": quote}
    if not isinstance(quote, dict):
        return None
    qtext = ac.text(quote.get("text")).strip()
    if not qtext:
        return None
    author = ac.text(quote.get("author")).strip()
    line = f"“{qtext}”"
    if author:
        line += f"  — {author}"
    return ac.paragraph_xml([ac.run_xml(line, italic=True)])


def bullet_block(
    parts: list[str], heading: str, values: object, *, keep_group: bool = False
) -> None:
    ac = agenda()
    items = [ac.text(v) for v in (values or []) if ac.text(v).strip()]
    if not items:
        return
    parts.append(ac.simple_paragraph(heading, style="Heading1"))
    for index, item in enumerate(items):
        if keep_group:
            parts.append(leveled_bullet(item, keep_next=index < len(items) - 1))
        else:
            parts.append(ac.simple_paragraph(item, bullet=True))


def takeaways_block(parts: list[str], takeaways: object) -> None:
    """Render the two reflection lists first, using real Word numbering."""
    ac = agenda()
    if not isinstance(takeaways, dict):
        return
    well = [ac.text(value) for value in (takeaways.get("well") or []) if ac.text(value).strip()]
    improve = [
        ac.text(value) for value in (takeaways.get("improve") or []) if ac.text(value).strip()
    ]
    if not well and not improve:
        return
    required = int(takeaways.get("required_items") or max(len(well), len(improve), 0))
    noun = "thing" if required == 1 else "things"
    if well:
        parts.append(
            ac.simple_paragraph(
                f"Yesterday — {required} {noun} I did well", style="Heading1"
            )
        )
        for item in well:
            parts.append(numbered_paragraph(item, 2))
    if improve:
        parts.append(
            ac.simple_paragraph(
                f"Today — {required} {noun} I can improve", style="Heading1"
            )
        )
        for item in improve:
            parts.append(numbered_paragraph(item, 3))


def numbered_paragraph(value: str, num_id: int) -> str:
    ac = agenda()
    p_props = [
        '<w:spacing w:after="60" w:line="280" w:lineRule="auto"/>',
        f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>',
    ]
    return f"<w:p><w:pPr>{''.join(p_props)}</w:pPr>{ac.run_xml(ac.text(value))}</w:p>"


def leveled_bullet(value: str, level: int = 0, keep_next: bool = False) -> str:
    ac = agenda()
    """A bullet paragraph at an explicit list level (0 = top, 1 = sub-bullet)."""
    p_props = [
        '<w:spacing w:after="60" w:line="280" w:lineRule="auto"/>',
        f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="1"/></w:numPr>',
    ]
    if keep_next:
        p_props.insert(0, "<w:keepNext/>")
    return f"<w:p><w:pPr>{''.join(p_props)}</w:pPr>{ac.run_xml(ac.text(value))}</w:p>"


def nested_bullet_block(parts: list[str], heading: str, values: object) -> None:
    ac = agenda()
    """Top-level bullets that may each carry a sub-bulleted list.

    Each entry is either a plain string (a single top-level bullet) or a dict
    ``{"text"/"action"/"label": ..., "sub_bullets": [...]}`` whose sub-bullets
    render one indent level deeper. Used for Top Action Items so the "send out
    next-day agendas" task can list the agendas to prep as sub-bullets.
    """
    items: list[tuple[str, int]] = []
    for entry in values or []:
        if isinstance(entry, dict):
            label = ac.text(entry.get("text") or entry.get("action") or entry.get("label")).strip()
            subs = [ac.text(s) for s in (entry.get("sub_bullets") or []) if ac.text(s).strip()]
            if not label and not subs:
                continue
            if label:
                items.append((label, 0))
            for sub in subs:
                items.append((sub, 1))
        else:
            label = ac.text(entry).strip()
            if label:
                items.append((label, 0))
    if not items:
        return
    parts.append(ac.simple_paragraph(heading, style="Heading1"))
    parts.extend(
        leveled_bullet(value, level, keep_next=index < len(items) - 1)
        for index, (value, level) in enumerate(items)
    )


def meetings_block(parts: list[str], values: object) -> None:
    ac = agenda()
    """Plan-day meeting schedule overview (times + titles), rendered as bullets.

    Each entry is a string (already formatted) or a dict with ``time``/``start``,
    ``title``/``subject``, and optional ``location``. A ``YYYY-MM-DDTHH:MM`` start
    is trimmed to ``HH:MM``.
    """
    lines: list[str] = []
    for meeting in values or []:
        if isinstance(meeting, dict):
            when = ac.text(meeting.get("time") or meeting.get("start")).strip()
            if "T" in when:
                when = when.split("T", 1)[1][:5]
            title = ac.text(meeting.get("title") or meeting.get("subject")).strip()
            location = ac.text(meeting.get("location")).strip()
            line = " — ".join(part for part in (when, title) if part)
            if location:
                line += f"  ({location})"
        else:
            line = ac.text(meeting).strip()
        if line:
            lines.append(line)
    if not lines:
        return
    parts.append(ac.simple_paragraph("Meeting Schedule", style="Heading1"))
    for line in lines:
        parts.append(leveled_bullet(line, 0))


def numbering_xml() -> str:
    """Compact-reference bullet and decimal numbering definitions."""
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="0">
    <w:multiLevelType w:val="hybridMultilevel"/>
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/>
      <w:numFmt w:val="bullet"/>
      <w:lvlText w:val="&#8226;"/>
      <w:lvlJc w:val="left"/>
      <w:pPr>
        <w:tabs><w:tab w:val="num" w:pos="540"/></w:tabs>
        <w:spacing w:after="80" w:line="300" w:lineRule="auto"/>
        <w:ind w:left="540" w:hanging="271"/>
      </w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="1">
      <w:start w:val="1"/>
      <w:numFmt w:val="bullet"/>
      <w:lvlText w:val="&#9702;"/>
      <w:lvlJc w:val="left"/>
      <w:pPr>
        <w:tabs><w:tab w:val="num" w:pos="1080"/></w:tabs>
        <w:spacing w:after="80" w:line="300" w:lineRule="auto"/>
        <w:ind w:left="1080" w:hanging="271"/>
      </w:pPr>
    </w:lvl>
  </w:abstractNum>
  <w:abstractNum w:abstractNumId="1">
    <w:multiLevelType w:val="singleLevel"/>
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/>
      <w:numFmt w:val="decimal"/>
      <w:lvlText w:val="%1."/>
      <w:lvlJc w:val="left"/>
      <w:pPr>
        <w:tabs><w:tab w:val="num" w:pos="540"/></w:tabs>
        <w:spacing w:after="80" w:line="300" w:lineRule="auto"/>
        <w:ind w:left="540" w:hanging="271"/>
      </w:pPr>
    </w:lvl>
  </w:abstractNum>
  <w:abstractNum w:abstractNumId="2">
    <w:multiLevelType w:val="singleLevel"/>
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/>
      <w:numFmt w:val="decimal"/>
      <w:lvlText w:val="%1."/>
      <w:lvlJc w:val="left"/>
      <w:pPr>
        <w:tabs><w:tab w:val="num" w:pos="540"/></w:tabs>
        <w:spacing w:after="80" w:line="300" w:lineRule="auto"/>
        <w:ind w:left="540" w:hanging="271"/>
      </w:pPr>
    </w:lvl>
  </w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
  <w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>
  <w:num w:numId="3"><w:abstractNumId w:val="2"/></w:num>
</w:numbering>
"""


def styles_xml() -> str:
    """Return compact_reference_guide with the dense_daily_plan rhythm override."""
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>
    <w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="280" w:lineRule="auto"/></w:pPr></w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:pPr><w:spacing w:after="80" w:line="280" w:lineRule="auto"/></w:pPr>
    <w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
    <w:pPr><w:keepNext/><w:spacing w:before="0" w:after="160"/></w:pPr>
    <w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:color w:val="0B2545"/><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle">
    <w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:after="120"/></w:pPr>
    <w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:i/><w:color w:val="666666"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
    <w:pPr><w:keepNext/><w:spacing w:before="280" w:after="140"/></w:pPr>
    <w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:color w:val="2E74B5"/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
    <w:pPr><w:keepNext/><w:spacing w:before="280" w:after="140"/></w:pPr>
    <w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:color w:val="2E74B5"/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading3">
    <w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
    <w:pPr><w:keepNext/><w:spacing w:before="200" w:after="100"/></w:pPr>
    <w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:b/><w:color w:val="1F4D78"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr>
  </w:style>
</w:styles>
"""


FOOTER_REL_ID = "rId100"
GTD_LINK_REL_ID = "rId101"


def footer_xml() -> str:
    """Return a muted right-aligned Page X of Y footer using Word fields."""
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p>
    <w:pPr><w:jc w:val="right"/></w:pPr>
    <w:r><w:rPr><w:color w:val="666666"/><w:sz w:val="18"/></w:rPr><w:t xml:space="preserve">Page </w:t></w:r>
    <w:r><w:rPr><w:color w:val="666666"/><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:rPr><w:color w:val="666666"/><w:sz w:val="18"/></w:rPr><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
    <w:r><w:rPr><w:color w:val="666666"/><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>
    <w:r><w:rPr><w:color w:val="666666"/><w:sz w:val="18"/></w:rPr><w:t xml:space="preserve"> of </w:t></w:r>
    <w:r><w:rPr><w:color w:val="666666"/><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:rPr><w:color w:val="666666"/><w:sz w:val="18"/></w:rPr><w:instrText xml:space="preserve"> NUMPAGES </w:instrText></w:r>
    <w:r><w:rPr><w:color w:val="666666"/><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>
  </w:p>
</w:ftr>
"""


def content_types_with_footer() -> str:
    ac = agenda()
    override = (
        '  <Override PartName="/word/footer1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>\n'
    )
    return ac.content_types_xml().replace("</Types>", override + "</Types>")


def document_rels(data: dict) -> str:
    ac = agenda()
    relationships: list[str] = []
    if data.get("page_numbers", True):
        relationships.append(
            f'  <Relationship Id="{FOOTER_REL_ID}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" '
            'Target="footer1.xml"/>\n'
        )
    gtd_link = data.get("gtd_link") or {}
    if gtd_link.get("url"):
        from xml.sax.saxutils import quoteattr

        relationships.append(
            f'  <Relationship Id="{GTD_LINK_REL_ID}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            f'Target={quoteattr(str(gtd_link["url"]))} TargetMode="External"/>\n'
        )
    return ac.document_rels_xml().replace(
        "</Relationships>", "".join(relationships) + "</Relationships>"
    )


def gtd_link_paragraph(value: object) -> str | None:
    ac = agenda()
    if not isinstance(value, dict):
        return None
    url = ac.text(value.get("url")).strip()
    if not url:
        return None
    label = ac.text(value.get("label") or "Open full GTD list").strip()
    from xml.sax.saxutils import escape

    run = (
        '<w:r><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr>'
        f"<w:t>{escape(label)}</w:t></w:r>"
    )
    return f'<w:p><w:hyperlink r:id="{GTD_LINK_REL_ID}">{run}</w:hyperlink></w:p>'


def daily_plan_body(data: dict) -> str:
    ac = agenda()
    parts: list[str] = []

    date = ac.text(data.get("date")).strip()
    parts.append(ac.simple_paragraph(f"Daily Plan — {date}" if date else "Daily Plan", style="Title"))

    takeaways_block(parts, data.get("takeaways"))

    quote = quote_paragraph(data.get("quote"))
    if quote:
        parts.append(quote)

    summary = ac.text(data.get("summary")).strip()
    if summary:
        parts.append(ac.simple_paragraph("Summary", style="Heading1"))
        parts.append(ac.simple_paragraph(summary))

    bullet_block(parts, "Meeting Insights", data.get("meeting_insights"), keep_group=True)

    gtd_link = gtd_link_paragraph(data.get("gtd_link"))
    if gtd_link:
        parts.append(gtd_link)

    mit = ac.text(data.get("mit")).strip()
    if mit:
        parts.append(ac.simple_paragraph("Most Important Task — “The Frog”", style="Heading1"))
        parts.append(ac.simple_paragraph(mit))

    bullet_block(parts, "Daily Big 3", data.get("daily_big_3"), keep_group=True)
    bullet_block(parts, "People Outreach", data.get("people_outreach"), keep_group=True)
    nested_bullet_block(parts, "Top Action Items", data.get("top_actions"))
    bullet_block(parts, "Other Action Items", data.get("other_actions"))
    meetings_block(parts, data.get("meetings"))

    return "\n".join(parts)


def document_xml(data: dict) -> str:
    body = daily_plan_body(data)
    footer_reference = (
        f'<w:footerReference w:type="default" r:id="{FOOTER_REL_ID}"/>'
        if data.get("page_numbers", True)
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    {body}
    <w:sectPr>
      {footer_reference}
      <w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""


def create_docx(data: dict, output_path: Path) -> None:
    ac = agenda()
    page_numbers = bool(data.get("page_numbers", True))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        docx.writestr(
            "[Content_Types].xml",
            content_types_with_footer() if page_numbers else ac.content_types_xml(),
        )
        docx.writestr("_rels/.rels", ac.root_rels_xml())
        docx.writestr(
            "word/_rels/document.xml.rels",
            document_rels(data),
        )
        docx.writestr("word/document.xml", document_xml(data))
        docx.writestr("word/styles.xml", styles_xml())
        docx.writestr("word/numbering.xml", numbering_xml())
        if page_numbers:
            docx.writestr("word/footer1.xml", footer_xml())


def load_data(args: argparse.Namespace) -> dict:
    if args.example:
        return EXAMPLE_DATA
    if not args.input:
        raise ValueError("Provide --input or --example")
    # utf-8-sig tolerates a BOM in case the payload was written by PowerShell.
    with Path(args.input).open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a combined Daily Plan Word document.")
    parser.add_argument("--input", help="Path to daily-plan JSON")
    parser.add_argument("--output", required=True, help="Path to write .docx")
    parser.add_argument(
        "--agenda-script",
        help="Path to agenda-creator's create_agenda_docx.py. Overrides CLOSE_DAY_AGENDA_SCRIPT.",
    )
    parser.add_argument("--example", action="store_true", help="Write an example Daily Plan document")
    args = parser.parse_args()

    try:
        global AGENDA_SCRIPT, ac
        if args.agenda_script:
            AGENDA_SCRIPT = Path(args.agenda_script)
            ac = load_agenda_module()
        data = load_data(args)
        create_docx(data, Path(args.output))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
