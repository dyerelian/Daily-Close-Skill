---
name: close-day
description: Close out Dan's workday using his GTD process — review and tidy the GTD workbook (mark done, flag overdue/stale, process inbox), sweep the day's loose ends from Slack, Atlassian, Granola/Outlook plus manual input into next actions/waiting-for/inbox, plan tomorrow's priorities, and save a dated end-of-day summary log. Invoked as "/close-day". Use when the user says close out my day, end of day, EOD, shut down, wrap up the day, daily review, or plan tomorrow.
---

# /close-day — End-of-Day GTD Close-Out

A **read-first, propose-then-confirm** shutdown ritual for Dan's GTD system. Gather state,
sweep the day's loose ends, plan tomorrow, ask Dan what else to capture, present **one**
consolidated proposal, and — only after a single approval — write workbook updates in place,
save a dated markdown log of *today*, and produce a forward-looking **Daily Plan Word
document for tomorrow**. Anything after `/close-day` (`$ARGUMENTS`) is Dan's free-text notes
for the day; fold it into the proposal.

This skill **orchestrates**; it does not re-implement the writer or the doc renderers. It reuses:

- Writer: `C:\Users\E724101\.claude\skills\add-gtd-items\scripts\Add-GtdItems.ps1`
- Columns, `Lists` vocabulary, defaults, payload schema: `C:\Users\E724101\.claude\skills\add-gtd-items\references\workbook-schema.md`
- External source conventions (narrow, recent, read-only): `C:\Users\E724101\.claude\skills\agenda-creator\references\context-sources.md`
- Tomorrow's meetings: `C:\Users\E724101\.claude\skills\close-day\scripts\Get-OutlookMeetings.ps1`
- Today's sent mail (for waiting-for sweep): `C:\Users\E724101\.claude\skills\close-day\scripts\Get-OutlookSentItems.ps1`
- Daily Plan renderer: `C:\Users\E724101\.claude\skills\close-day\scripts\create_daily_plan_docx.py`

Two daily artifacts (distinct on purpose):
- **EOD markdown log** — retrospective record of *today* (`...\GTD Daily Logs\EOD YYYY-MM-DD.md`).
- **Daily Plan `.docx`** — forward-looking plan for *tomorrow* (`...\Daily Plan\Daily Plan YYYY-MM-DD.docx`).

Live workbook:
`C:\Users\E724101\OneDrive - Automobile Club of Southern California\Dan Yerelian - GTD - $add-gtd-items.xlsx`

## Workflow

### Phase 1 — Read current GTD state (read-only)

Load the writable sheets with `Import-Excel` (EPPlus; already installed — never Excel COM,
never hand-write OpenXML). Use today's date from `currentDate` (e.g. `2026-06-26`).

```powershell
Import-Module ImportExcel
$wb = "C:\Users\E724101\OneDrive - Automobile Club of Southern California\Dan Yerelian - GTD - `$add-gtd-items.xlsx"
$actions  = Import-Excel -Path $wb -WorksheetName 'Next Actions'
$waiting  = Import-Excel -Path $wb -WorksheetName 'Waiting For'
$inbox    = Import-Excel -Path $wb -WorksheetName 'Inbox'
$projects = Import-Excel -Path $wb -WorksheetName 'Projects'
```

Compute, relative to today:
- **Overdue actions** — `Next Actions` with `Due Date` < today and `Status` not in {Complete, Canceled}.
- **Due/scheduled today** — `Due Date` = today or `Scheduled Date` = today.
- **Stale waiting-for** — `Waiting For` with `Follow-up Date` ≤ today and `Status` = Waiting.
- **Waiting-for due to follow up next** — `Waiting For` with `Follow-up Date` = the **target day**
  (next working day) and `Status` = Waiting. These need a follow-up nudge tomorrow, so each becomes
  a `next_actions` item scheduled for the target day (see Phase 4 → Follow-ups).
- **Unprocessed inbox** — `Inbox` rows with `Processed? = No`.
- **Projects needing review** — open projects with an old `Last Reviewed` or no open next action.
- **Completed-today candidates** — actions Dan's notes or the source sweep show as finished.

### Phase 2 — Sweep the day's loose ends (read-only)

Follow `agenda-creator/references/context-sources.md`: searches stay narrow, recent, and
**strictly read-only** — never post to Slack, send mail, or modify Jira/Confluence/Granola.
Scan **today only**:
- **Slack** — mentions, DMs, and active project channels for asks / commitments / follow-ups.
- **Atlassian** — Jira issues assigned to or updated by Dan today; relevant Confluence activity.
- **Granola / Outlook** — today's meetings and notes for action items and waiting-for commitments.
- **Outlook Sent Mail** — mail Dan sent today, to catch questions / requests he is now waiting on
  a reply for. Run the bundled COM reader (defaults to today):
  ```powershell
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\E724101\.claude\skills\close-day\scripts\Get-OutlookSentItems.ps1" `
    -OutFile "$env:TEMP\sent-today.json"
  ```
  The script emits `{ date, dayOfWeek, count, messages:[ { sentOn, subject, to, cc, recipients,
  containsQuestion, body } ] }`. Prioritize `containsQuestion: true` messages but read each body —
  for any mail where Dan **asked someone a question or requested something and owes nothing further
  himself**, propose a `waiting_for` entry: `Who` = the recipient(s), `What` = the ask, a
  `Follow-up Date` (default ~2–3 working days out unless the mail implies a deadline), and the
  subject/quote in `notes`. Skip pure FYIs, newsletters, and replies where Dan owns the next step
  (those are `next_actions`). On `error`/`count: 0`, note it and move on.

Map findings to GTD entry types using the `add-gtd-items` classification:
- Dan owns a concrete next step → `next_actions`
- someone else owns the next move → `waiting_for`
- capture-only / unclear → `inbox`

Keep raw wording in `notes`; summarize long threads concisely.

### Phase 2b — Plan tomorrow (read-only)

Build the inputs for the Daily Plan document. The plan targets the **next working day**, which is
usually tomorrow but may not be.

**Two relevant days, do not conflate them:**
- **Target day** — the day the Daily Plan is *for* (usually tomorrow). This is `<target-day>` everywhere below.
- **Agenda send-out day** — the **next working day _after_ the target day**. Dan sends agendas and
  pre-reads **24 hours ahead**, so on the target-day morning his **first task** is to send out the
  agendas/pre-reads for the agenda send-out day's meetings. (Example: closing out on Monday, the
  target day is Tuesday and the agenda send-out day is Wednesday — Tuesday's first task is to send
  Wednesday's agendas.) Across weekends/holidays this is still the next *working* day (e.g. on a
  Friday plan, the send-out day is Monday).

1. **Read the target day's meetings** via Outlook COM (defaults to tomorrow):
   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\E724101\.claude\skills\close-day\scripts\Get-OutlookMeetings.ps1" `
     -OutFile "$env:TEMP\tomorrow-meetings.json"
   ```
   The script emits JSON `{ date, dayOfWeek, isWeekend, suggestedTargetDay, holidayHints, count,
   meetings:[…] }`. **Determine which day to prep for:**
   - If `isWeekend` is true, or `holidayHints` is non-empty, or you otherwise know the next day is a
     holiday / Dan is off, **ask Dan which day to prep for**, offering `suggestedTargetDay` (the next
     weekday) as the recommended default.
   - Once the target day is chosen, **re-run the script with that date** and use it everywhere as the
     plan day:
     ```powershell
     powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\E724101\.claude\skills\close-day\scripts\Get-OutlookMeetings.ps1" `
       -Date 2026-06-29 -OutFile "$env:TEMP\tomorrow-meetings.json"
     ```
   - If the script exits non-zero / includes an `error`, or returns `count: 0` unexpectedly for a
     workday, **fall back to asking Dan to paste the target day's meetings**.
   - The target day's meetings are for the plan's **schedule overview** (so Dan sees his day). Their
     agendas were already sent out the prior working day, so do **not** re-draft them here.
2. **Read the agenda send-out day's meetings** — re-run the same script for the next working day
   *after* the target day, since these are the agendas Dan sends out 24h ahead on the target morning:
   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\E724101\.claude\skills\close-day\scripts\Get-OutlookMeetings.ps1" `
     -Date <agenda-send-out-day> -OutFile "$env:TEMP\sendout-meetings.json"
   ```
   If that day is a weekend/holiday (check `isWeekend` / `holidayHints`), step to the next working day
   (use `suggestedTargetDay`) and re-run so the send-out day is always a real working day.
3. **Draft an agenda for each agenda send-out day meeting** — gather context per
   `agenda-creator/references/context-sources.md` and produce the same agenda structure
   `create_agenda_docx.py` expects (`title`, `send_ahead_bullets` [5–10 words, max 10],
   `context_reviewed`, `sections[]`, `notes[]`). These render into the combined Daily Plan doc so they
   are ready for Dan to send out on the target-day morning. (If the send-out day has no meetings, draft
   none and skip the send task in step 4.)
4. **Derive MIT / "The Frog"** — the single highest-impact / hardest item for the target day (from
   P1 / overdue / due-soon actions, project milestones, and the day's sweep).
5. **Set the first task of the target day** — if the send-out day has meetings (step 2/3), the target
   day's **first scheduled action** is always: *"Send out agendas & pre-reads for `<agenda-send-out-day>`
   meetings (24h ahead): `<list meeting titles>`."* It leads the top-actions list and is scheduled for
   the target day.
6. **Derive the Daily Big 3** — three concrete *outcomes* for the target day (distinct from the task list).
7. **Pick one inspirational quote** (text + author) for the top of the page; if a recent file in
   the `Daily Plan` folder exists, avoid repeating its quote.

### Phase 3 — Ask Dan for manual inputs

After displaying the gathered items (so he has context), explicitly ask:
**"Anything else to capture, close, or carry into tomorrow?"** Fold his answers into the proposal.

### Phase 4 — Present ONE consolidated proposal (the single confirmation gate)

Render a clean, sectioned summary and wait for approval. Dan can edit or drop any line first.
- **Mark complete** — actions to set `Status = Complete`, `Completed = today` (update by `id`).
- **New captures** — proposed `next_actions` / `waiting_for` / `inbox` rows (classification + defaults).
- **Process inbox** — proposed `Decision` (Do/Delegate/Defer/Delete/Clarify/Incubate) + next step.
- **Follow-ups** — new `next_actions` generated from waiting-for items: both **stale** ones
  (`Follow-up Date` ≤ today) and ones **due to follow up on the target day**. Schedule each follow-up
  action for the target day (`Scheduled Date = target day`) so it lands in tomorrow's plan, and name
  the person + the ask (e.g. *"Follow up with Mariyo re: vendor SOW (sent 6/26)"*).
- **Tomorrow's plan** — actions to set `Scheduled Date = tomorrow`; a prioritized top-3
  (by `Priority` P1→P4, due dates, blockers); the proposed **MIT / "The Frog"**, **Daily Big 3**,
  the inspirational quote, the target day's Outlook meetings (schedule overview), and — as the
  **first task** — *send out agendas & pre-reads for the agenda send-out day's meetings* (the
  next working day after the target), with those agendas drafted and ready in the Daily Plan doc.
- **Project reviews** — projects to stamp `Last Reviewed = today`.
- **Daily log preview** — the markdown (today) that will be saved.
- **Daily Plan preview** — the quote, summary, MIT, Big 3, action lists, and per-meeting agenda
  outlines (tomorrow) that will be rendered into the combined `.docx`.

### Phase 5 — Execute (after approval only)

1. **Build the JSON payload** (arrays: `next_actions`, `waiting_for`, `inbox`, plus updates that
   carry an existing `id`). Use `Lists` vocabulary values and ISO dates. Write the file with the
   `Write` tool (or `[System.IO.File]::WriteAllText(...)` with no-BOM UTF-8) — never
   `Set-Content -Encoding utf8`. Suggested path: `$env:TEMP\close-day-payload.json`.
   When the agenda send-out day has meetings, include the **send-agendas task** as a `next_actions`
   row (`Scheduled Date = <target-day>`, high priority) so it lands in the workbook as the target
   day's first action — e.g. *"Send out agendas & pre-reads for `<send-out day>` meetings."*

2. **Dedup-check first:**
   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\E724101\.claude\skills\add-gtd-items\scripts\Add-GtdItems.ps1" `
     -PayloadFile "$env:TEMP\close-day-payload.json" -DryRun
   ```
   If it reports likely duplicates, **pause and ask** update-vs-add (reuse the `id` to update).

3. **Write in place:**
   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\E724101\.claude\skills\add-gtd-items\scripts\Add-GtdItems.ps1" `
     -PayloadFile "$env:TEMP\close-day-payload.json" -InPlace
   ```
   Confirm `validated: true` in the script output.

4. **Save the daily log** with the `Write` tool to:
   `C:\Users\E724101\OneDrive - Automobile Club of Southern California\GTD Daily Logs\EOD YYYY-MM-DD.md`
   Sections: **Accomplished today · Captured · Carried to tomorrow (top priorities) · Waiting on · Notes**.
   If a file for today already exists, **append a timestamped section** rather than overwriting.

5. **Generate the target day's Daily Plan `.docx`.** Build the daily-plan JSON and write it BOM-free
   to `$env:TEMP\daily-plan.json` (use the target day chosen in Phase 2b for `date` and the filename):
   ```json
   {
     "date": "YYYY-MM-DD (target day)",
     "quote": { "text": "...", "author": "..." },
     "summary": "1-3 sentence framing of the target day",
     "mit": "single most important task",
     "daily_big_3": ["outcome 1", "outcome 2", "outcome 3"],
     "top_actions": ["Send out agendas & pre-reads for <send-out day> meetings (24h ahead)", "A-012 ...", "A-031 ..."],
     "other_actions": ["..."],
     "agendas": [ { "title": "...", "send_ahead_bullets": ["..."], "context_reviewed": ["..."], "sections": [ … ], "notes": ["..."] } ]
   }
   ```
   `top_actions[0]` is the send-out task (when the send-out day has meetings); `agendas[]` are the
   **agenda send-out day's** meeting agendas (target+1 working day), ready for Dan to send out 24h ahead.
   Then render (creates the `Daily Plan` folder if missing):
   ```powershell
   & 'C:\Program Files\Python312\python.exe' "C:\Users\E724101\.claude\skills\close-day\scripts\create_daily_plan_docx.py" `
     --input "$env:TEMP\daily-plan.json" `
     --output "C:\Users\E724101\OneDrive - Automobile Club of Southern California\Daily Plan\Daily Plan <target-day>.docx"
   ```
   A non-zero exit usually means a `send_ahead_bullets` failed the 5–10-word rule — fix and re-run.

6. **Report** one line per change (sheet, ID, title, added/updated/completed) + the EOD log path
   + the Daily Plan `.docx` path + the count of meeting agendas included. Excel rollups/Dashboard
   refresh when the workbook is next opened.

## Defaults & guardrails

- Reuse the **`add-gtd-items` writer**; never hand-write `.xlsx` OpenXML (Excel COM is broken here).
- **Never write Projects columns K/L/M** (live rollup formulas) — the writer protects these.
- Use **`Lists` vocabulary** for Status/Priority/Area/Context/Decision/etc. (e.g. Status `Complete`,
  Priority `P1 - Must`, Decision `Defer`).
- **Always `-DryRun` dedup-check before writing**; pause on likely duplicates. OneDrive keeps history.
- External sources are **read-only** — never post, send, or modify external items.
- Use **ISO dates** in the payload; exact names for owners/people (e.g. `Mariyo`).
- One approval gate only: gather everything, propose once, then execute.
- **Outlook access via the bundled PowerShell COM script only** (late-bound IDispatch). Never use
  Python `win32com`/`EnsureDispatch` — the typelib/gencache path is broken on this machine. Calendar
  reads are read-only; never send or modify Outlook items.
- The Daily Plan renderer is **stdlib-only** Python via the full interpreter path
  `C:\Program Files\Python312\python.exe` (never bare `py`); it reuses `agenda-creator`'s
  `create_agenda_docx.py` helpers, so agenda rendering stays identical.
