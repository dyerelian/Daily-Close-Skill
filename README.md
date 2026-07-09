# Daily Close Skill (`/close-day`)

A [Claude Code](https://claude.ai/code) **skill** that runs an end-of-day GTD (Getting Things
Done) close-out ritual. It reviews the GTD workbook, reviews how today's committed priorities
landed, sweeps the day's loose ends from Slack, Teams, Atlassian, and Granola/Outlook (plus
Outlook Sent Mail), plans the next working day, and produces two dated artifacts: a
retrospective **EOD markdown log** and a forward-looking **Daily Plan Word document** (plus
ready-to-send standalone meeting agendas).

The skill is **read-first and propose-then-confirm**: it gathers everything, presents one
consolidated proposal, and only writes anything after a single approval.

## What it does

Invoked as `/close-day` (optionally with free-text notes for the day), it runs as a sequence of
phases:

0. **Preflight** — probes the MCP connectors the sweep depends on (Slack, Atlassian, Granola)
   and tells Dan up front if any are down (expired auth, wrong scope, server off) so the sweep
   is never silently incomplete.
1. **Read current GTD state** — loads the GTD Excel workbook and computes overdue actions, items
   due/scheduled today, stale waiting-for items, waiting-for items due to follow up the next day,
   unprocessed inbox items, projects needing review, and **today's committed priorities** (what
   the previous close scheduled for today).
2. **Sweep the day's loose ends** (read-only) — Slack, **Teams** (local-cache reader),
   Atlassian (Jira/Confluence), Granola/Outlook meetings & notes, and **Outlook Sent Mail** (to
   catch questions/requests Dan is now waiting on). Findings are classified into next actions,
   waiting-for, or inbox captures. It also **plans the next working day** (target-day meeting
   schedule + full agendas) and **confirms how today's committed priorities landed** (done /
   carried / dropped / changed), then asks Dan for any manual captures and tomorrow's priorities.
3. **Present one consolidated proposal** — the single confirmation gate. Dan can edit or drop any line.
4. **Execute (after approval only)** — writes workbook updates in place via the `add-gtd-items`
   writer, refreshes each affected project's **canonical Confluence page** (the only external
   write, and only after approval), saves the EOD markdown log, renders the Daily Plan `.docx`,
   and writes the send-out day's agendas as standalone `.docx` files.

### Target day vs. agenda send-out day

Agendas go out **24 hours ahead**, so the close distinguishes two days:

- **Target day** — the day the Daily Plan is *for* (usually tomorrow).
- **Agenda send-out day** — the next working day *after* the target day. The target morning's
  first task is always to send out that day's agendas, which this close drafts in full and writes
  as standalone files so the morning task is a true *send*, not a draft-then-send.

## Repository contents

| Path | Purpose |
|------|---------|
| `SKILL.md` | The skill definition and full workflow (loaded by Claude Code). |
| `scripts/Get-OutlookMeetings.ps1` | Reads a day's Outlook calendar appointments → JSON. Late-bound COM, read-only. |
| `scripts/Get-OutlookSentItems.ps1` | Reads a day's Outlook Sent Mail → JSON (flags messages containing questions) for the waiting-for sweep. Late-bound COM, read-only. |
| `scripts/Get-TeamsMessages.py` | Best-effort read-only extraction of the day's Teams chat from the local new-Teams IndexedDB cache → JSON. |
| `scripts/vendor/` | Vendored, MIT-licensed [`ccl_chromium_reader`](https://github.com/cclgroupltd/ccl_chromium_reader) (CCL Forensics) — a pure-Python Chromium IndexedDB/LevelDB reader used by `Get-TeamsMessages.py`. See [Attribution](#attribution-vendored-code). |
| `scripts/create_daily_plan_docx.py` | Renders the combined Daily Plan `.docx` from structured JSON. Standard-library Python only. |

## Key design choices

- **Agendas go out 24 hours ahead.** The Daily Plan for the target day prepares and prompts sending
  the *next* working day's agendas as the first task of the morning.
- **Sent Mail → Waiting For.** Mail where Dan asked a question or made a request (and owes nothing
  further) becomes a proposed `Waiting For` entry with a follow-up date.
- **Teams is best-effort and read-only.** There is no Teams MCP/Graph/COM on the host, so the
  skill parses the local new-Teams IndexedDB (LevelDB) cache. The schema is undocumented and can
  change with Teams updates, so on any error/empty result the skill falls back to asking Dan to
  paste the relevant chats — it never blocks the close-out.
- **One approval gate.** Nothing is written to the workbook, Confluence, log, or doc until Dan
  approves the single consolidated proposal.
- **External sources are read-only during the sweep.** The skill never posts to Slack/Teams, sends
  mail, or modifies Jira/Granola while gathering. The **only** external write is the approved
  canonical Confluence page refresh/move in the execute phase.

## Dependencies

This skill orchestrates rather than re-implements, and relies on companion pieces on the host machine:

- **Sibling Claude Code skills** (referenced by absolute path in `SKILL.md`):
  - `add-gtd-items` — the workbook writer (`Add-GtdItems.ps1`), the workbook schema reference, and
    the `canonical-project-page.md` reference used to refresh Confluence pages.
  - `agenda-creator` — `create_agenda_docx.py`, whose OpenXML helpers `create_daily_plan_docx.py`
    imports so agenda rendering stays identical. **The Daily Plan renderer will not run without it.**
- **Tooling:** Windows + a locally installed/configured Outlook (late-bound COM; `win32com`/
  `EnsureDispatch` is intentionally avoided), the new **Microsoft Teams** desktop client (for the
  local IndexedDB cache), Python 3.12 (invoked by full path), and the `ImportExcel` PowerShell
  module (EPPlus) for reading the workbook.
- **MCP servers** for the sweep: Slack, Atlassian, Granola. (Teams and Outlook are *not* MCP — they
  use the bundled scripts.)

## Installation

Copy the contents into a Claude Code skills directory (e.g. `~/.claude/skills/close-day/`) so the
layout is `close-day/SKILL.md` and `close-day/scripts/...`, then invoke `/close-day`.

> **Note on paths:** `SKILL.md` and the Python renderer contain absolute Windows paths specific to
> the original author's machine (workbook location, sibling-skill scripts, Python interpreter).
> Adjust these for your environment before use.

## Sync model (junction)

On the author's machine this repo is the **single source of truth**, and the live skill under
`~/.claude/skills/close-day` is a **directory junction** pointing at the repo root — so editing in
either place touches the same files, with no copying and no drift.

```
~/.claude/skills/close-day  ──junction──▶  <repo root>
```

Workflow: edit wherever's convenient, then commit/push from the repo:

```powershell
cd ~/repos/Daily-Close-Skill
git add -A; git commit -m "..."; git push
```

(Re)create the junction on this machine — or on a fresh clone — with:

```powershell
$live = Join-Path $env:USERPROFILE '.claude\skills\close-day'
$repo = $PSScriptRoot   # the cloned repo's root
if (Test-Path $live) { Remove-Item $live -Recurse -Force }
New-Item -ItemType Junction -Path $live -Target $repo | Out-Null
```

Notes:
- Directory junctions need **no admin rights or Developer Mode** on Windows and are transparent to
  Claude Code, which reads `SKILL.md`/`scripts/` and ignores the repo's `README.md`/`.gitignore`.
- Junctions are local to a machine — they don't travel with the repo. On a new machine, clone then
  run the snippet above (or just copy the contents into `~/.claude/skills/close-day/`).

## Attribution (vendored code)

`scripts/vendor/` bundles [`ccl_chromium_reader`](https://github.com/cclgroupltd/ccl_chromium_reader)
by CCL Forensics, redistributed under the **MIT License** (the full license header is retained in
each source file). It is used only to read the local Teams IndexedDB cache; it is not modified.
