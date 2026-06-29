# Daily Close Skill (`/close-day`)

A [Claude Code](https://claude.ai/code) **skill** that runs an end-of-day GTD (Getting Things
Done) close-out ritual. It reviews the GTD workbook, sweeps the day's loose ends from Slack,
Atlassian, Granola/Outlook, and Outlook Sent Mail, plans the next working day, and produces two
dated artifacts: a retrospective **EOD markdown log** and a forward-looking **Daily Plan Word
document**.

The skill is **read-first and propose-then-confirm**: it gathers everything, presents one
consolidated proposal, and only writes anything after a single approval.

## What it does

Invoked as `/close-day` (optionally with free-text notes for the day), it runs five phases:

1. **Read current GTD state** — loads the GTD Excel workbook and computes overdue actions, items
   due/scheduled today, stale waiting-for items, waiting-for items due to follow up the next day,
   unprocessed inbox items, and projects needing review.
2. **Sweep the day's loose ends** (read-only) — Slack, Atlassian (Jira/Confluence), Granola/Outlook
   meetings & notes, and **Outlook Sent Mail** (to catch questions/requests Dan is now waiting on).
   Findings are classified into next actions, waiting-for, or inbox captures.
3. **Plan the next working day** — reads the target day's meetings for a schedule overview, drafts
   ready-to-send agendas for the **agenda send-out day** (the next working day *after* the target,
   because agendas go out 24h ahead), and derives the MIT ("The Frog"), the Daily Big 3, the day's
   first task (send out those agendas), and an inspirational quote.
4. **Present one consolidated proposal** — the single confirmation gate. Dan can edit or drop any line.
5. **Execute (after approval only)** — writes workbook updates in place via the `add-gtd-items`
   writer, saves the EOD markdown log, and renders the Daily Plan `.docx`.

## Repository contents

| Path | Purpose |
|------|---------|
| `SKILL.md` | The skill definition and full workflow (loaded by Claude Code). |
| `scripts/Get-OutlookMeetings.ps1` | Reads a day's Outlook calendar appointments → JSON. Late-bound COM, read-only. |
| `scripts/Get-OutlookSentItems.ps1` | Reads a day's Outlook Sent Mail → JSON (flags messages containing questions) for the waiting-for sweep. Late-bound COM, read-only. |
| `scripts/create_daily_plan_docx.py` | Renders the combined Daily Plan `.docx` from structured JSON. Standard-library Python only. |

## Key design choices

- **Agendas go out 24 hours ahead.** The Daily Plan for the target day prepares and prompts sending
  the *next* working day's agendas as the first task of the morning.
- **Sent Mail → Waiting For.** Mail where Dan asked a question or made a request (and owes nothing
  further) becomes a proposed `Waiting For` entry with a follow-up date.
- **One approval gate.** Nothing is written to the workbook, log, or doc until Dan approves the
  single consolidated proposal.
- **All external sources are strictly read-only** — the skill never posts to Slack, sends mail, or
  modifies Jira/Confluence/Granola/Outlook items.

## Dependencies

This skill orchestrates rather than re-implements, and relies on companion pieces on the host machine:

- **Sibling Claude Code skills** (referenced by absolute path in `SKILL.md`):
  - `add-gtd-items` — the workbook writer (`Add-GtdItems.ps1`) and workbook schema reference.
  - `agenda-creator` — `create_agenda_docx.py`, whose OpenXML helpers `create_daily_plan_docx.py`
    imports so agenda rendering stays identical. **The Daily Plan renderer will not run without it.**
- **Tooling:** Windows + a locally installed/configured Outlook (late-bound COM; `win32com`/
  `EnsureDispatch` is intentionally avoided), Python 3.12 (invoked by full path), and the
  `ImportExcel` PowerShell module (EPPlus) for reading the workbook.
- **MCP servers** for the sweep: Slack, Atlassian, Granola.

## Installation

Copy the contents into a Claude Code skills directory (e.g. `~/.claude/skills/close-day/`) so the
layout is `close-day/SKILL.md` and `close-day/scripts/...`, then invoke `/close-day`.

> **Note on paths:** `SKILL.md` and the Python renderer contain absolute Windows paths specific to
> the original author's machine (workbook location, sibling-skill scripts, Python interpreter).
> Adjust these for your environment before use.
