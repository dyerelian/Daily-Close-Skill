---
name: close-day
description: Close out Dan's workday using his GTD process — review and tidy the GTD workbook (mark done, flag overdue/stale, process inbox), review how today's committed priorities landed, sweep the day's loose ends from Slack, Teams, Atlassian, Granola/Outlook plus manual input into next actions/waiting-for/inbox, plan tomorrow's priorities, and save a dated end-of-day summary log. Invoked as "/close-day". Use when the user says close out my day, end of day, EOD, shut down, wrap up the day, daily review, or plan tomorrow.
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
- **EOD markdown log** — retrospective record of *today* (`...\Daily Plan\GTD Daily Logs\EOD YYYY-MM-DD.md`).
- **Daily Plan `.docx`** — forward-looking plan for *tomorrow* (`...\Daily Plan\Daily Plan YYYY-MM-DD.docx`).
- **Standalone target-day agendas** — one `.docx` per target-day meeting, written into the shared
  Agendas folder (`...\Daily Plan\Agendas\<YYYY_MM_DD>\<HHMM> <Title>.docx`) so they exist as
  individual files, not only embedded in the Daily Plan doc.

Live workbook:
`C:\Users\E724101\OneDrive - Automobile Club of Southern California\Dan Yerelian - GTD - $add-gtd-items.xlsx`

## Workflow

### Phase 0 — Preflight: confirm MCP connectors are live (read-only)

Before gathering anything, verify the MCP connectors this close-out depends on are actually
loaded **and authenticated**. A connector can be configured yet silently fail — expired token,
wrong project scope, server not running — which makes the Phase 2 sweep quietly incomplete. The
sweep depends on three MCP connectors: **Slack**, **Atlassian** (`my-atlassian`), and **Granola**.
(Teams and Outlook are **not** MCP — they use the bundled COM / local-cache scripts and keep their
own fallbacks, so they are out of scope for this check.)

For each, run one cheap read-only probe and confirm it returns real data rather than an
auth/entitlement error or a "tool not found":
- **Slack** — e.g. `list_channels` (limit 1). `{"ok": false, "error": "invalid_auth"}` — or the
  `slack` tools not being present at all — means Slack is down.
- **Atlassian** — a lightweight call (e.g. current-user / accessible-resources, or a 1-row JQL). A
  401/auth error means it's down.
- **Granola** — e.g. `recent_notes` (limit 1). An error or a missing tool means it's down.

If any connector is missing or failing, **tell Dan up front which are down and what it costs**,
then let him steer — never silently proceed. For example:

> ⚠️ Slack and Granola aren't responding (auth/expired). If we proceed now, today's Slack and
> Granola sweep will be skipped. Fix: re-auth via `/mcp`, then fully restart Claude Code (the
> Slack token lives in `C:\Users\E724101\slack-mcp\.env`; config changes only load at startup) —
> or I can proceed with reduced context and you paste anything important.

Ask whether to **(a) pause so he can fix/re-auth and restart**, or **(b) proceed with the available
sources**. If proceeding, note the skipped connector(s) explicitly in the EOD log's **Notes**
section so the gap is on the record. Degrade gracefully — a down connector reduces context, it does
not block the close-out.

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
- **Today's committed priorities** — `Next Actions` with `Scheduled Date` = today (the items the
  *previous* close scheduled as today's priorities). Split them by `Status`:
  - `Complete` / `Canceled` → **resolved**, no need to ask.
  - Still open (`Not Started` / `In Progress` / etc.) that the day's sweep or Dan's notes **do
    clearly show** as finished → treat as a completed-today candidate.
  - Still open and **not** clearly evidenced as done → **needs a status update from Dan**
    (handled in Phase 2c). This is how the close reviews whether yesterday's plan actually happened.

### Phase 2 — Sweep the day's loose ends (read-only)

Follow `agenda-creator/references/context-sources.md`: searches stay narrow, recent, and
**strictly read-only** — never post to Slack, send mail, or modify Jira/Confluence/Granola.
Scan **today only**:
- **Slack** — mentions, DMs, and active project channels for asks / commitments / follow-ups.
- **Teams** — recent 1:1 / group chat for asks, commitments, and follow-ups. Run the bundled
  reader (read-only, best-effort local-cache extraction; defaults to today):
  ```powershell
  & 'C:\Program Files\Python312\python.exe' "C:\Users\E724101\.claude\skills\close-day\scripts\Get-TeamsMessages.py" `
    --out "$env:TEMP\teams-today.json"
  ```
  It emits `{ date, dayOfWeek, count, warning, messages:[ { sentOn, from, chat, messageType,
  isSentByCurrentUser, containsQuestion, body } ] }`. Use `isSentByCurrentUser` to tell Dan's own
  messages from others'. Map `containsQuestion` / commitment messages the same way as the mail
  sweep: someone owes Dan a reply → `waiting_for`; Dan owes the next step → `next_actions`;
  unclear → `inbox`. **If the script errors, warns, or returns `count: 0`, fall back to asking Dan
  to paste any relevant Teams chats** (mirrors the "paste the meetings" fallback) and move on — the
  local Teams cache is undocumented and may not always parse.
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
   - The target day's meetings feed **both** the plan's **schedule overview** (the "Meeting Schedule"
     section, so Dan sees his day) **and** the full detailed **Meeting Agendas** — these are Dan's prep
     for the meetings he is actually attending that day (drafted in step 3).
2. **Read the agenda send-out day's meetings** — re-run the same script for the next working day
   *after* the target day (i.e. **two days out** from the close). These are the agendas Dan must
   **send out** 24h ahead on the target morning, so they are **drafted in full here** and written as
   standalone `.docx` files into the send-out day's Agendas folder (Phase 5 step 6) — ready to send,
   not draft-then-send. They **also** feed the send-out task's sub-bullets (titles + times) in step 5:
   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\E724101\.claude\skills\close-day\scripts\Get-OutlookMeetings.ps1" `
     -Date <agenda-send-out-day> -OutFile "$env:TEMP\sendout-meetings.json"
   ```
   If that day is a weekend/holiday (check `isWeekend` / `holidayHints`), step to the next working day
   (use `suggestedTargetDay`) and re-run so the send-out day is always a real working day.
   **Draft a full agenda for each substantive send-out-day meeting** — same context-gathering and
   agenda structure as step 3 (`title`, `send_ahead_bullets`, `context_reviewed`, `sections[]`,
   `notes[]`). These become the standalone send-out-day agenda files in Phase 5 step 6.
3. **Draft a full agenda for each substantive target-day meeting** (the day the plan is *for*) — gather
   context per `agenda-creator/references/context-sources.md` and produce the same agenda structure
   `create_agenda_docx.py` expects (`title`, `send_ahead_bullets` [5–10 words, max 10],
   `context_reviewed`, `sections[]`, `notes[]`). These become `agendas[]` and render (one per page) in
   the **Meeting Agendas** section after the Meeting Schedule, so Dan walks into today's meetings
   prepared. Skip pure-social blocks (e.g. lunches), all-day blocks, and non-meeting reminders. (The
   send-out day's meetings from step 2 are drafted in full too, but as **standalone files** in the
   send-out-day Agendas folder — see Phase 5 step 6 — and also appear as the send-out task's
   sub-bullet titles in step 5. They are **not** embedded in the target-day Daily Plan doc.)
4. **Derive MIT / "The Frog"** — the single highest-impact / hardest item for the target day (from
   P1 / overdue / due-soon actions, project milestones, and the day's sweep).
5. **Set the first task of the target day** — if the send-out day has meetings (step 2/3), the target
   day's **first scheduled action** is always: *"Send out agendas & pre-reads for `<agenda-send-out-day>`
   meetings (24h ahead): `<list meeting titles>`."* It leads the top-actions list and is scheduled for
   the target day. In the Daily Plan doc this renders as the first Top Action Item with **one
   sub-bullet per send-out meeting agenda to prep** (title + time), so Dan sees exactly what to send
   (see Phase 5 step 5 `top_actions` object form). Because those agendas were **drafted in full this
   close** (step 2) and written as standalone files (step 6), the morning task is a true *send*, not a
   draft-then-send.
6. **Derive the Daily Big 3** — three concrete *outcomes* for the target day (distinct from the task list).
7. **Pick one inspirational quote** (text + author) for the top of the page; if a recent file in
   the `Daily Plan` folder exists, avoid repeating its quote.

### Phase 2c — Confirm how today's priorities landed

Using **Today's committed priorities** from Phase 1, close the loop on the *previous* plan before
building tomorrow's. For every committed priority that is already **resolved** (Status
Complete/Canceled) or clearly evidenced as done by the sweep, record the outcome silently — do
**not** ask about these.

For the remaining **open** priorities / today's action items, **ask Dan about each one at a time**
(one question per item, sequentially — do not batch them into a single list). For each item ask
whether he accomplished it, e.g.:

> **"Did you accomplish `<action>` today? (done / carried / dropped / changed)"**

Wait for his answer before moving to the next item. If there are no open items to confirm, **skip
this step entirely**. Fold Dan's answers into the proposal (Phase 4): done → mark complete;
unfinished → carry forward to the target day; dropped → cancel; changed → update the action.

### Phase 3 — Ask Dan for manual inputs

After displaying the gathered items (so he has context), explicitly ask:
**"Anything else to capture, close, or carry into tomorrow?"** Fold his answers into the proposal.

Then, as a distinct follow-up, **explicitly ask Dan whether he wants to prioritize anything for the
next day** — e.g. **"Anything you want to prioritize for tomorrow?"** — and fold his answer into
Tomorrow's plan (Phase 2b/4): the named items become the top-priority scheduled actions / MIT /
Daily Big 3 for the target day. Ask this even if the automatic derivation already produced a
top-3, so Dan's own priorities take precedence.

### Phase 4 — Present ONE consolidated proposal (the single confirmation gate)

Render a clean, sectioned summary and wait for approval. Dan can edit or drop any line first.
- **Today's priorities review** — for each of today's committed priorities (Phase 1 / 2c): its
  outcome (done / carried / dropped / changed). Route each into the right action below — done →
  Mark complete; carried → Tomorrow's plan (reschedule to the target day); dropped → cancel;
  changed → update.
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
- **Completed projects** — projects set to a done status get their canonical Confluence
  page moved from the `Active Projects` to the `Closed Projects` index list (and page
  Status flipped to Closed). See `add-gtd-items/references/canonical-project-page.md`.
- **Canonical page updates** — every project with a **material change today** (status,
  a decision, a milestone reached, a new risk/open question, or a new next-action /
  waiting-for tied to it) gets its canonical Confluence page refreshed to match —
  Overview table, Milestones, Decisions, and the reverse-chronological Updates log —
  because Confluence is the public source of truth. Merge, never overwrite. See
  `add-gtd-items/references/canonical-project-page.md` → "Updating an existing page."
- **Daily log preview** — the markdown (today) that will be saved.
- **Daily Plan preview** — the quote, summary, MIT, Big 3, action lists (with the send-out day
  agendas as titles-only sub-bullets under the first Top Action Item), the target day's **Meeting
  Schedule** overview, and the target day's full per-meeting agenda outlines (Dan's prep for today's
  meetings) that will be rendered into the combined `.docx`.

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

   **3b. Refresh canonical Confluence pages.** For each project in the approved proposal
   with a material change today (and for completed projects, the Active→Closed move),
   update its canonical page per
   `add-gtd-items/references/canonical-project-page.md` → "Updating an existing page":
   read the page ID from the project's `notes` (`Canonical page: <url>`),
   `confluence_get_page`, **merge** the change into the Overview / Milestones / Decisions
   / Updates sections (never blank a section), then `confluence_update_page`. This is the
   only external write in the close-out, and it happens only after the single approval gate.

4. **Save the daily log** with the `Write` tool to:
   `C:\Users\E724101\OneDrive - Automobile Club of Southern California\Daily Plan\GTD Daily Logs\EOD YYYY-MM-DD.md`
   Sections: **Accomplished today · Captured · Carried to tomorrow (top priorities) · Waiting on · Notes**.
   Reflect the **Today's priorities review** (Phase 2c) here: resolved priorities go under
   *Accomplished today*, and any that Dan carried forward go under *Carried to tomorrow*.
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
     "top_actions": [
       { "text": "Send out agendas & pre-reads for <send-out day> meetings (24h ahead)",
         "sub_bullets": ["<send-out meeting 1 (time)>", "<send-out meeting 2 (time)>"] },
       "A-012 ...", "A-031 ..."
     ],
     "other_actions": ["..."],
     "meetings": [ { "start": "YYYY-MM-DDTHH:MM", "subject": "...", "location": "..." } ],
     "agendas": [ { "title": "...", "send_ahead_bullets": ["..."], "context_reviewed": ["..."], "sections": [ … ], "notes": ["..."] } ]
   }
   ```
   - `top_actions[0]` is the send-out task (when the send-out day has meetings). Make it an **object**
     with `sub_bullets` — one sub-bullet per **agenda send-out day** meeting you need to prep (title +
     time) — so the agendas to put together render as an indented sub-list under Top Action Items.
     These are **titles only** (not full agendas). (Any `top_actions`/`other_actions` entry may be a
     plain string or `{ "text", "sub_bullets" }`.)
   - `meetings` is the **target day's own schedule** (the Phase 2b step 1 Outlook meetings) — a
     schedule overview that renders as its own "Meeting Schedule" section **after Other Action Items**
     and before the full agendas. Skip all-day blocks and non-meeting reminders. `start` may be a full
     `…THH:MM` (trimmed to `HH:MM`) or a bare time string.
   - `agendas[]` are the **target day's own** meeting agendas (the day the plan is for), drafted in
     full and rendered (one per page) in the **Meeting Agendas** section right after Meeting Schedule —
     Dan's prep for today's meetings. (The send-out day's agendas are *not* rendered in full; they are
     only the sub-bullet titles under `top_actions[0]`.)

   Document order top→bottom: quote · title · summary · MIT · Daily Big 3 · Top Action Items (with
   send-out day sub-bullets) · Other Action Items · **Meeting Schedule (target day)** · Meeting Agendas
   (target day, full detail).
   Then render (creates the `Daily Plan` folder if missing):
   ```powershell
   & 'C:\Program Files\Python312\python.exe' "C:\Users\E724101\.claude\skills\close-day\scripts\create_daily_plan_docx.py" `
     --input "$env:TEMP\daily-plan.json" `
     --output "C:\Users\E724101\OneDrive - Automobile Club of Southern California\Daily Plan\Daily Plan <target-day>.docx"
   ```
   A non-zero exit usually means a `send_ahead_bullets` failed the 5–10-word rule — fix and re-run.

6. **Write the SEND-OUT day's agendas as standalone `.docx` files** into the shared Agendas folder
   (the day **two days out** from the close), so tomorrow morning's "send agendas 24h ahead" task is a
   true send — the files already exist. Use the per-meeting agenda objects drafted in Phase 2b step 2.
   Write each to its own BOM-free JSON and render it with `agenda-creator`'s renderer. Follow the
   agenda-creator naming and location rules exactly (dated subfolder `YYYY_MM_DD` = **send-out day**;
   filename `<HHMM> <Title>.docx` with the meeting's 24-hour start time; sanitize illegal characters;
   `0000` when no known time):
   ```powershell
   $dated = '<send-out-day as YYYY_MM_DD>'
   $agendaDir = "C:\Users\E724101\OneDrive - Automobile Club of Southern California\Daily Plan\Agendas\$dated"
   New-Item -ItemType Directory -Force -Path $agendaDir | Out-Null
   # for each send-out-day agenda (drafted in Phase 2b step 2):
   & 'C:\Program Files\Python312\python.exe' "C:\Users\E724101\.claude\skills\agenda-creator\scripts\create_agenda_docx.py" `
     --input "$env:TEMP\agenda-<n>.json" `
     --output "$agendaDir\<HHMM> <Title>.docx"
   ```
   The **target day's** own standalone agenda folder is *not* (re)created here — it was already
   produced by the **previous** close (when the target day was that close's send-out day). The
   target-day agendas still render **embedded** in the Daily Plan doc (step 5, `agendas[]`) as Dan's
   prep for the meetings he attends that day. Net: each close writes **one** standalone folder — the
   send-out day (two days out) — and **one** Daily Plan doc — the target day (tomorrow).

7. **Report** one line per change (sheet, ID, title, added/updated/completed) + the EOD log path
   + the Daily Plan `.docx` path + the Agendas-folder path with the count of standalone agenda
   files written + the count of meeting agendas embedded. Excel rollups/Dashboard refresh when the
   workbook is next opened.

## Defaults & guardrails

- Reuse the **`add-gtd-items` writer**; never hand-write `.xlsx` OpenXML (Excel COM is broken here).
- **Never write Projects columns K/L/M** (live rollup formulas) — the writer protects these.
- Use **`Lists` vocabulary** for Status/Priority/Area/Context/Decision/etc. (e.g. Status `Complete`,
  Priority `P1 - Must`, Decision `Defer`).
- **Always `-DryRun` dedup-check before writing**; pause on likely duplicates. OneDrive keeps history.
- External sources are **read-only during the sweep** — never post, send, or modify
  external items while gathering (Phases 1–3). The **only** external write is the
  approved canonical Confluence page refresh/move in Phase 5 (step 3b), after the
  single approval gate.
- Use **ISO dates** in the payload; exact names for owners/people (e.g. `Mariyo`).
- One approval gate only: gather everything, propose once, then execute.
- **Outlook access via the bundled PowerShell COM script only** (late-bound IDispatch). Never use
  Python `win32com`/`EnsureDispatch` — the typelib/gencache path is broken on this machine. Calendar
  reads are read-only; never send or modify Outlook items.
- **Teams is read-only, best-effort local-cache extraction** via the bundled `Get-TeamsMessages.py`
  (there is no Teams MCP / Graph SDK / COM here). The IndexedDB schema is undocumented and can change
  with Teams updates — **never post to Teams**, and on any error/empty result fall back to asking Dan
  to paste the relevant chats.
- The Daily Plan renderer is **stdlib-only** Python via the full interpreter path
  `C:\Program Files\Python312\python.exe` (never bare `py`); it reuses `agenda-creator`'s
  `create_agenda_docx.py` helpers, so agenda rendering stays identical.
