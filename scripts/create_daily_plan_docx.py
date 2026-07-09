#!/usr/bin/env python3
"""Render a combined "Daily Plan" Word document from structured JSON.

The Daily Plan is the forward-looking output of the `close-day` skill. Its layout,
top to bottom, is:

    inspirational quote  ->  title/date  ->  summary  ->  MIT ("The Frog")  ->
    Daily Big 3  ->  top action items  ->  other action items  ->
    one full agenda section per meeting (each on its own page)

Per-meeting agendas are rendered with the EXACT same logic as the `agenda-creator`
skill: this script imports `create_agenda_docx.py` as a module and reuses its
OpenXML helpers (run/paragraph builders, `document_body`, the package-part writers,
and the 5-10-word send-ahead-bullet validation). Standard library only.

Run with the full interpreter path (bare `py` is broken on this machine):
    & 'C:\\Program Files\\Python312\\python.exe' create_daily_plan_docx.py --input plan.json --output "Daily Plan 2026-06-27.docx"
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import zipfile
from pathlib import Path


AGENDA_SCRIPT = Path(
    r"C:\Users\E724101\.claude\skills\agenda-creator\scripts\create_agenda_docx.py"
)


def load_agenda_module():
    """Load create_agenda_docx.py as a module so its helpers can be reused."""
    if not AGENDA_SCRIPT.exists():
        raise FileNotFoundError(f"agenda-creator script not found: {AGENDA_SCRIPT}")
    spec = importlib.util.spec_from_file_location("agenda_creator", AGENDA_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # safe: the module guards main() behind __main__
    return module


ac = load_agenda_module()


EXAMPLE_DATA = {
    "date": "2026-06-27",
    "quote": {
        "text": "Either you run the day or the day runs you.",
        "author": "Jim Rohn",
    },
    "summary": "Light meeting load; protect the morning for the funnel write-up.",
    "mit": "Draft the AAA customer-acquisition funnel one-pager (hardest, highest leverage).",
    "daily_big_3": [
        "Funnel one-pager drafted and shared for review",
        "Q3 roadmap input sent to Mariyo",
        "Inbox back to zero",
    ],
    "top_actions": [
        {
            "text": "Send out tomorrow's agendas & pre-reads (24h ahead)",
            "sub_bullets": [
                "1:1 with Mariyo",
                "Team backlog refinement",
            ],
        },
        "A-012 Draft funnel one-pager",
        "A-031 Send roadmap input to Mariyo",
        "A-044 Review vendor SOW",
    ],
    "other_actions": [
        "A-051 Book travel for the offsite",
        "A-052 Reply to finance on the PO",
    ],
    "meetings": [
        {"start": "2026-06-27T09:30", "subject": "Project Prioritization Weekly Update"},
        {"start": "2026-06-27T10:00", "subject": "1:1 with Mariyo", "location": "Motor Sports"},
        {"start": "2026-06-27T14:00", "subject": "Team backlog refinement"},
    ],
    "agendas": [
        {
            "title": "1:1 with Mariyo - 2026-06-27",
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
                        {"label": "My focus", "body": "Funnel one-pager and roadmap input."},
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


def bullet_block(parts: list[str], heading: str, values: object) -> None:
    items = [ac.text(v) for v in (values or []) if ac.text(v).strip()]
    if not items:
        return
    parts.append(ac.simple_paragraph(heading, style="Heading1"))
    for item in items:
        parts.append(ac.simple_paragraph(item, bullet=True))


def leveled_bullet(value: str, level: int = 0) -> str:
    """A bullet paragraph at an explicit list level (0 = top, 1 = sub-bullet)."""
    p_props = [
        '<w:spacing w:after="120"/>',
        f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="1"/></w:numPr>',
    ]
    return f"<w:p><w:pPr>{''.join(p_props)}</w:pPr>{ac.run_xml(ac.text(value))}</w:p>"


def nested_bullet_block(parts: list[str], heading: str, values: object) -> None:
    """Top-level bullets that may each carry a sub-bulleted list.

    Each entry is either a plain string (a single top-level bullet) or a dict
    ``{"text"/"action"/"label": ..., "sub_bullets": [...]}`` whose sub-bullets
    render one indent level deeper. Used for Top Action Items so the "send out
    next-day agendas" task can list the agendas to prep as sub-bullets.
    """
    block: list[str] = []
    for entry in values or []:
        if isinstance(entry, dict):
            label = ac.text(entry.get("text") or entry.get("action") or entry.get("label")).strip()
            subs = [ac.text(s) for s in (entry.get("sub_bullets") or []) if ac.text(s).strip()]
            if not label and not subs:
                continue
            if label:
                block.append(leveled_bullet(label, 0))
            for sub in subs:
                block.append(leveled_bullet(sub, 1))
        else:
            label = ac.text(entry).strip()
            if label:
                block.append(leveled_bullet(label, 0))
    if not block:
        return
    parts.append(ac.simple_paragraph(heading, style="Heading1"))
    parts.extend(block)


def meetings_block(parts: list[str], values: object) -> None:
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
    """Two-level bullet numbering (level 0 + sub-bullet level 1) on numId 1.

    Overrides the agenda-creator's single-level numbering so Top Action Items can
    nest agenda sub-bullets; level 0 stays identical, so reused agenda rendering
    (which only uses ilvl 0 on numId 1) is unaffected.
    """
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="0">
    <w:multiLevelType w:val="hybridMultilevel"/>
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/>
      <w:numFmt w:val="bullet"/>
      <w:lvlText w:val="&#8226;"/>
      <w:lvlJc w:val="left"/>
      <w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="1">
      <w:start w:val="1"/>
      <w:numFmt w:val="bullet"/>
      <w:lvlText w:val="&#9702;"/>
      <w:lvlJc w:val="left"/>
      <w:pPr><w:ind w:left="1440" w:hanging="360"/></w:pPr>
    </w:lvl>
  </w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>
"""


def daily_plan_body(data: dict) -> str:
    parts: list[str] = []

    quote = quote_paragraph(data.get("quote"))
    if quote:
        parts.append(quote)

    date = ac.text(data.get("date")).strip()
    parts.append(ac.simple_paragraph(f"Daily Plan — {date}" if date else "Daily Plan", style="Title"))

    summary = ac.text(data.get("summary")).strip()
    if summary:
        parts.append(ac.simple_paragraph("Summary", style="Heading1"))
        parts.append(ac.simple_paragraph(summary))

    mit = ac.text(data.get("mit")).strip()
    if mit:
        parts.append(ac.simple_paragraph("Most Important Task — “The Frog”", style="Heading1"))
        parts.append(ac.simple_paragraph(mit))

    bullet_block(parts, "Daily Big 3", data.get("daily_big_3"))
    nested_bullet_block(parts, "Top Action Items", data.get("top_actions"))
    bullet_block(parts, "Other Action Items", data.get("other_actions"))
    meetings_block(parts, data.get("meetings"))

    agendas = data.get("agendas") or []
    if agendas:
        parts.append(ac.simple_paragraph("Meeting Agendas", style="Heading1"))
        for agenda in agendas:
            if not isinstance(agenda, dict):
                continue
            parts.append(page_break())
            # Reuse the exact agenda rendering (also validates send-ahead bullets).
            parts.append(ac.document_body(agenda))

    return "\n".join(parts)


def document_xml(data: dict) -> str:
    body = daily_plan_body(data)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {body}
    <w:sectPr>
      <w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""


def create_docx(data: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", ac.content_types_xml())
        docx.writestr("_rels/.rels", ac.root_rels_xml())
        docx.writestr("word/_rels/document.xml.rels", ac.document_rels_xml())
        docx.writestr("word/document.xml", document_xml(data))
        docx.writestr("word/styles.xml", ac.styles_xml())
        docx.writestr("word/numbering.xml", numbering_xml())


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
    parser.add_argument("--example", action="store_true", help="Write an example Daily Plan document")
    args = parser.parse_args()

    try:
        data = load_data(args)
        create_docx(data, Path(args.output))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
