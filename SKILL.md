---
name: close-day
description: Close out Dan's workday using his GTD process — review and tidy the GTD workbook (mark done, flag overdue/stale, process inbox), review how today's committed priorities landed, sweep the day's loose ends from Slack, Teams, Atlassian, Granola/Outlook plus manual input into next actions/waiting-for/inbox, capture daily takeaways (3 wins / 3 improvements), plan tomorrow's priorities, and save a dated end-of-day summary log. Invoked as "/close-day". Use when the user says close out my day, end of day, EOD, shut down, wrap up the day, daily review, or plan tomorrow.
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
- Canonical Confluence page mechanics (create / update / close): `C:\Users\E724101\.claude\skills\source-of-truth\references\canonical-project-page.md`
- Meeting-first page fan-out (route a day's meetings to their canonical pages): `C:\Users\E724101\.claude\skills\source-of-truth\references\meeting-sweep.md` (used by Phase 2e)
- Tomorrow's meetings: `C:\Users\E724101\.claude\skills\close-day\scripts\Get-OutlookMeetings.ps1`
- Today's sent mail (for waiting-for sweep): `C:\Users\E724101\.claude\skills\close-day\scripts\Get-OutlookSentItems.ps1`
- Daily Plan renderer: `C:\Users\E724101\.claude\skills\close-day\scripts\create_daily_plan_docx.py`

Both daily artifacts open with a **Daily Takeaways** reflection — 3 things Dan did well
today and 3 things to change/improve next time (Brian Tracy's end-of-day discipline).
Claude drafts them from the day's signals; Dan edits them at the single approval gate.

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
- **Canonical page coverage / staleness** — from the `Projects` sheet, flag (a) active
  (non-done) projects whose `notes` has **no** `Canonical page:` URL (missing a source-of-truth
  page), and (b) projects with a material change today whose canonical page's latest `Updates`
  entry predates that change (stale). These feed the "Canonical page coverage" proposal line
  (Phase 4); creating/refreshing uses the `source-of-truth` skill in Phase 5 step 3b.
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

**Per-meeting agenda direction (Dan steers each agenda — gather once, reuse across closes).**
Dan can give short per-meeting direction that shapes the drafted agendas. Because the same meeting
surfaces twice — first as a **send-out-day** agenda (two nights out, step 2) and again the next night
as **target-day** prep (step 3) — his direction is **captured once and reused**, never re-asked. The
store write below is Dan's own captured input (a local file), not an external side effect, so it is
allowed during the otherwise read-only gather.

- **Direction store.** Persist direction in
  `C:\Users\E724101\OneDrive - Automobile Club of Southern California\Daily Plan\meeting-directions.json`
  (survives across closes — never `$env:TEMP`). Key each entry by the meeting instance:
  normalized `subject` + `|` + the actual start `YYYY-MM-DDTHH:MM` — the same calendar instance keeps
  the same key on both nights, so reuse is automatic. Entry shape:
  ```json
  { "key": "Weekly Membership Sync|2026-08-04T10:00", "subject": "Weekly Membership Sync",
    "start": "2026-08-04T10:00", "goal": "...", "include": "...", "reference_prior": "...",
    "decisions_asks": "...", "review_items": "...", "raw_blurb": "<Dan's verbatim text>",
    "skip": false, "captured_on": "2026-08-02", "used_on": ["2026-08-02", "2026-08-03"] }
  ```
  On load, **prune** entries whose `start` is before today so the file stays small. Write it BOM-free
  with the `Write` tool (or `[System.IO.File]::WriteAllText(...)`) — never `Set-Content -Encoding utf8`.

- **Gather loop — run after reading the meetings (steps 1–2), before drafting (steps 2–3).**
  Build the union of target-day + send-out-day meetings and apply the **same skip rules as Phase 2e**
  (AAA-only by content / attendees / project — **never** the organizer email; drop all-day / holiday /
  pure-social blocks). For each surviving meeting, look up its key in the store:
  - **Stored entry exists → reuse silently** (no re-prompt); append today to `used_on`. This is how
    target-day prep inherits the direction Dan gave two nights earlier as a send-out agenda.
  - **No entry → prompt fresh**, one meeting at a time (mirror the Phase 2c / 2e sequential
    one-at-a-time convention — one question per meeting, wait for the answer, never batch). Show the
    meeting's context first (subject, day/time, attendees, a short `body` snippet from
    `Get-OutlookMeetings.ps1`), then ask:
    > For **"<subject>" (<day> <time>)** — what's the **goal**? what should be **included**? **which
    > previous information** should I reference (prior meeting/agenda, doc, data)? any **decisions or
    > asks** to land? any **specific items to review**? — or say **skip** to let me auto-draft it.

    Every field is optional. Save each answer to the store as captured (`skip` → store `"skip": true`
    so the meeting isn't re-prompted next close and just auto-drafts). Meetings with no direction and
    those Dan skips still get a full auto-drafted agenda from pulled context, exactly as today.

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
   `notes[]`). These become the standalone send-out-day agenda files in Phase 5 step 6. When the
   meeting has a stored direction entry (see "Per-meeting agenda direction" above), **fold Dan's
   direction in with precedence** over auto-pulled context — `goal` → the agenda `subtitle` / a
   leading "Purpose & desired outcome" item and the `send_ahead_bullets` framing; `include` /
   `review_items` → discussion `sections[].items`; `decisions_asks` → a "Decisions needed / asks"
   section; `reference_prior` → both which sources to pull and a `context_reviewed[]` note (e.g.
   "Per Dan's direction: reviewed <prior meeting/doc>"). Auto-context fills gaps but never overrides
   Dan's explicit instruction. `send_ahead_bullets` still obey the 5–10-word, max-10 rule.
3. **Draft a full agenda for each substantive target-day meeting** (the day the plan is *for*) — gather
   context per `agenda-creator/references/context-sources.md` and produce the same agenda structure
   `create_agenda_docx.py` expects (`title`, `send_ahead_bullets` [5–10 words, max 10],
   `context_reviewed`, `sections[]`, `notes[]`). For recurring meetings (1:1s, standing syncs), open
   the agenda with a **Last meeting recap** built per that reference's "Recurring meetings:
   prior-instance & recap sourcing" procedure — chain to the prior instance's agenda `.docx` in the
   Agendas folder plus its Granola note so open follow-ups carry forward. These become `agendas[]` and render (one per page) in
   the **Meeting Agendas** section after the Meeting Schedule, so Dan walks into today's meetings
   prepared. Fold in any stored per-meeting direction with precedence, exactly as in step 2 — a
   single captured direction produces consistent content in both the standalone send-out file and
   this embedded agenda. Skip pure-social blocks (e.g. lunches), all-day blocks, and non-meeting reminders. (The
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

### Phase 2d — Draft the Daily Takeaways (Brian Tracy reflection)

Brian Tracy's end-of-day discipline: close every day by naming **3 things you did well**
and **3 things you'll change or improve next time**. From the day's signals — completed
priorities and wins, the sweep (Slack/Teams/Atlassian/Granola/mail), blockers, dropped or
slipped items, and Dan's Phase 2c answers — **draft a proposed 3 "did well" + 3 "to improve
next time."** These are Claude's drafts; Dan edits, replaces, or trims them at the single
approval gate (Phase 4). Keep each a concrete, specific one-liner (not "had a good day").
If the day genuinely yields fewer than three of either, propose what's real rather than
padding.

### Phase 2e — Meeting-first canonical page sweep (read-only routing)

Phase 1's "Canonical page coverage / staleness" flags pages **project-first** (a project shows a
material change today). This phase adds the **meeting-first** pass so a substantive call whose
narrative never became a GTD change still reaches its canonical page. Follow
`source-of-truth\references\meeting-sweep.md` — this is routing only; **no page is written here**
(writes happen in Phase 5 step 3b behind the single gate).

> **This phase runs on every close — never skip it, including retroactive / backfill closes.**
> The routing loop is what guarantees a meeting like a new partner intro (e.g. Albertsons) is
> surfaced instead of silently dropped. Even when the page **writes** are deferred or skipped for a
> backfill, still **run the routing** (Step D) so each substantive AAA meeting gets a decision, and
> **record the deferred routing decisions in the EOD log's Notes** (which page each meeting should
> create/update) so the follow-up write isn't lost. Only the *writes* may be deferred behind the
> gate — the *surfacing* always happens.

1. **Enumerate today's meetings.** Run `Get-OutlookMeetings.ps1 -Date <today ISO>` (it defaults to
   tomorrow — pass today explicitly) and **UNION** with the Phase 2 Granola `recent_notes` results
   already pulled in the sweep (reuse them; do not re-query). Correlate calendar block ↔ Granola
   note by start-time overlap + fuzzy title; dedupe recurring/duplicate blocks.
2. **Skip / scope.** Drop all-day / holiday / pure-social blocks. **Surface 1:1s in the routing
   loop** (don't hard-skip). Apply the **AAA-only scope** — skip non-AAA meetings, judging
   relevance by **content / attendees / project match, never the organizer or note-owner email**.
3. **Build the page universe once** — reuse Phase 1's loaded `$projects` (column O
   `Canonical page:` URLs) plus the Active/Closed index `<li>` enumeration; key by `pageId`.
4. **Route each surviving meeting with the sequential one-at-a-time confirm** (mirror Phase 2c —
   one question per meeting, never batched): `Meeting "<subject>" (<time>). Best match: <page>.
   [1] update this page  [2] different existing page  [3] new page  [4] skip. Recommended: [n]`.
5. **Reconcile into the shared per-page work list keyed by `pageId`** that Phase 1's staleness
   flags populate: a meeting hitting an already-flagged page **merges into that entry** (one page,
   project + meeting facts folded together); a meeting-only page becomes a **new entry**; a
   "new page" decision becomes a create entry. No page appears twice.

### Phase 2f — Direct-report 1:1 trackers (read-only extraction)

Dan keeps a **confidential, local 1:1 tracker** per direct report. When the target day's meetings
(the Phase 2e enumeration — calendar ∪ Granola) include a **1:1 with one of the three reports**,
refresh that person's tracker. This is **routing/extraction only** here; the write happens in Phase 5
step 4b behind the single gate.

Roster and tracker paths (each is a JSON source + a rendered `.docx`, under
`…\OneDrive - Automobile Club of Southern California\_Documents\my Team\Team Yerelian\`):
- **Mike Mehrer** — `Mike\Mike Mehrer - 1-1 Tracker.json` / `.docx`
- **Mariyo Kamiya** — `Mariyo\Mariyo Kamiya - 1-1 Tracker.json` / `.docx`
- **Joey Lee** — `Joey\Joey Lee - 1-1 Tracker.json` / `.docx`

For each 1:1 with a rostered report on the target day:
1. **Locate the Granola note** for that 1:1 (title like `<Name> 1:1`) by start-time overlap with the
   calendar block — these notes' AI **summaries are null**, so read the **transcript**
   (`get_transcript`), correlating created_at to the meeting slot (UTC meeting-start, −7h PDT) per the
   Granola-timestamp habit. **If no transcript exists**, don't invent one — ask Dan for the recap +
   action items in Phase 3 (manual inputs).
2. **Extract** from the transcript: new action items (with owners), a short discussion recap, any
   candidate **wins** and **watch items**, and which prior open items are now **done**.
3. **Stage the tracker edit** (propose in Phase 4, don't write yet): read the person's `.json`, then —
   - prepend new action items to **Open Action Items**, each prefixed `[<meeting date ISO>]`
     (owner named if not the report); mark/remove ones now complete;
   - move the current **Last 1:1 - <old date>** section's gist into a one-line **1:1 History** entry,
     and replace it with **Last 1:1 - <new date>** (the new recap bullets);
   - add any confirmed **Wins & Recognition** / **Watch Items** bullets (dated);
   - bump the `subtitle` `Updated <today>`.

This runs **only** when a rostered 1:1 is on the target day — no rostered 1:1, no tracker work.
**Confidential + local**: never route a tracker to Confluence or the Phase 2e page universe.
Only the read-only Granola extraction may be delegated to a subagent — **never** the proposal
(a fork will confabulate Dan's calls); Dan confirms every staged tracker edit at the gate.

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
- **Daily Takeaways** (Phase 2d) — the drafted **3 things done well** + **3 to improve next
  time**, explicitly flagged as editable so Dan tweaks/replaces them before approving. These
  land at the top of both today's EOD log and tomorrow's Daily Plan doc.
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
- **Direct-report 1:1 trackers** (Phase 2f) — only when a 1:1 with Mike Mehrer, Mariyo Kamiya, or
  Joey Lee is on the target day. Per report, show the staged tracker edit: new dated action items,
  items now complete, the new **Last 1:1** recap (with the prior recap collapsing into 1:1 History),
  and any candidate Wins / Watch items. Editable — Dan drops/tweaks any line before approving.
- **Completed projects** — projects set to a done status get their canonical Confluence
  page moved from the `Active Projects` to the `Closed Projects` index list (and page
  Status flipped to Closed). See the `source-of-truth` skill's
  `references/canonical-project-page.md`.
- **Canonical page updates** — the **merged per-page work list** (Phase 1 project-driven flags
  **plus** Phase 2e meeting-first routing, deduped by `pageId`). Each page appears **once**, with
  project facts and any meeting narrative folded together, refreshed to match — Overview table,
  Milestones, Decisions, and the reverse-chronological Updates log — because Confluence is the
  public source of truth. This now surfaces **meeting-only** narrative (a call's decision/pivot
  that produced no GTD change), not just project-tagged changes. Merge, never overwrite. See the
  `source-of-truth` skill's `references/canonical-project-page.md` → "Updating an existing page"
  and `references/meeting-sweep.md`.
- **Canonical page coverage** — active projects flagged in Phase 1 as **missing** a
  canonical page, plus any **new page** decisions from the Phase 2e meeting routing (propose
  creating each via the `source-of-truth` skill) and any pages flagged **stale** (propose a
  refresh). Skip this line if none were flagged.
- **Meeting direction** — one line per upcoming agenda showing whether it used *newly captured*
  direction, *reused* direction (from a prior close), or *auto-draft (skipped)*, so Dan sees his
  instructions reflected before approving. Editable — he can revise any blurb at this gate.
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

   **3b. Refresh canonical Confluence pages.** Process the **merged per-page work list** from the
   proposal (Phase 1 project-driven flags **plus** Phase 2e meeting-first routing, deduped by
   `pageId`) — **one `confluence_get_page → merge → confluence_update_page` per `pageId`**, so a
   page hit by both a project change and a meeting is fetched and written exactly once with both
   sets of facts and a single dated Updates bullet. Merge per the `source-of-truth` skill's
   `references/canonical-project-page.md` → "Updating an existing page" (Overview / Milestones /
   Decisions / Risks / Updates; never blank a section; respect the ~20K condense exception and
   the page content rules — attribute to "the meeting" and its date, never name/link Granola, no
   GTD keys). For any **missing-page** project or **new-page** meeting decision approved in the
   "Canonical page coverage" line, create the page first (same skill → "Creating a page for a new
   project"), append its `<li>` to the Active index, and store the URL in the project's `notes`
   (column O) via the `add-gtd-items` writer if it is GTD-tracked. For completed projects, do the
   Active→Closed move. This is the only external write in the close-out, and it happens only after
   the single approval gate.

4. **Save the daily log** with the `Write` tool to:
   `C:\Users\E724101\OneDrive - Automobile Club of Southern California\Daily Plan\GTD Daily Logs\EOD YYYY-MM-DD.md`
   Sections, in order: **Daily Takeaways · Accomplished today · Captured · Carried to tomorrow
   (top priorities) · Waiting on · Notes**. `## Daily Takeaways` is the **first H2, immediately
   after the H1 title** — the approved 3 did-well + 3 to-improve (Phase 2d/4), rendered as two
   short lists (e.g. bold **Did well** and **To improve next time** sub-labels, each with its
   bullets). Reflect the **Today's priorities review** (Phase 2c) in the rest: resolved
   priorities go under *Accomplished today*, and any that Dan carried forward go under
   *Carried to tomorrow*. If a file for today already exists, **append a timestamped section**
   rather than overwriting.

   **4b. Refresh direct-report 1:1 trackers** (only when a rostered 1:1 was on the target day and Dan
   approved the staged edit in Phase 4). For each such report: apply the approved changes to the
   person's tracker **`.json`** (Open Action Items, Last 1:1 / 1:1 History, Wins, Watch Items, and the
   `Updated` date) with the `Write` tool (BOM-free) — the JSON is the source of truth; never hand-edit
   the `.docx`. Then re-render:
   ```powershell
   & 'C:\Program Files\Python312\python.exe' "C:\Users\E724101\.claude\skills\agenda-creator\scripts\create_agenda_docx.py" `
     --input  "…\my Team\Team Yerelian\<Folder>\<Name> - 1-1 Tracker.json" `
     --output "…\my Team\Team Yerelian\<Folder>\<Name> - 1-1 Tracker.docx"
   ```
   Confirm a `Wrote …` line / exit 0. These files stay **local** — never publish them to Confluence.

5. **Generate the target day's Daily Plan `.docx`.** Build the daily-plan JSON and write it BOM-free
   to `$env:TEMP\daily-plan.json` (use the target day chosen in Phase 2b for `date` and the filename):
   ```json
   {
     "date": "YYYY-MM-DD (target day)",
     "quote": { "text": "...", "author": "..." },
     "summary": "1-3 sentence framing of the target day",
     "takeaways": { "source_day": "YYYY-MM-DD (the day being closed)", "well": ["...", "...", "..."], "improve": ["...", "...", "..."] },
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

   - `takeaways` is the approved Daily Takeaways (Phase 2d/4). `source_day` is the **day being
     closed** (the prior working day relative to the target day), so tomorrow's plan opens by
     carrying forward today's reflection. Omit the key (or leave both lists empty) to skip the
     section — the renderer no-ops on empty input.

   Document order top→bottom: quote · title · summary · **Daily Takeaways (from the day being
   closed)** · MIT · Daily Big 3 · Top Action Items (with send-out day sub-bullets) · Other Action
   Items · **Meeting Schedule (target day)** · Meeting Agendas (target day, full detail).
   Then render (creates the `Daily Plan` folder if missing):
   ```powershell
   & 'C:\Program Files\Python312\python.exe' "C:\Users\E724101\.claude\skills\close-day\scripts\create_daily_plan_docx.py" `
     --input "$env:TEMP\daily-plan.json" `
     --output "C:\Users\E724101\OneDrive - Automobile Club of Southern California\Daily Plan\Daily Plan <target-day>.docx"
   ```
   A non-zero exit usually means a `send_ahead_bullets` failed the 5–10-word rule — fix and re-run.
   The renderer **always adds a centered "Page X of Y" footer** to every page of the Daily Plan
   (PAGE/NUMPAGES fields) — this is built into `create_daily_plan_docx.py`, so no payload flag is
   needed; the multi-page plan is always paginated.

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
   files written + the count of meeting agendas embedded + a one-line direction summary (how many
   agendas used newly-captured vs. reused vs. auto-drafted direction) + any direct-report 1:1
   trackers refreshed (Phase 2f/4b). Excel rollups/Dashboard refresh when the workbook is next opened.

## Defaults & guardrails

- Reuse the **`add-gtd-items` writer**; never hand-write `.xlsx` OpenXML (Excel COM is broken here).
- **Never write Projects columns K/L/M** (live rollup formulas) — the writer protects these.
- Use **`Lists` vocabulary** for Status/Priority/Area/Context/Decision/etc. (e.g. Status `Complete`,
  Priority `P1 - Must`, Decision `Defer`).
- **Always `-DryRun` dedup-check before writing**; pause on likely duplicates. OneDrive keeps history.
- External sources are **read-only during the sweep** — never post, send, or modify
  external items while gathering (Phases 1–3, including the Phase 2e meeting-first routing,
  which decides page targets but writes nothing). The **only** external write is the
  approved canonical Confluence page refresh/move in Phase 5 (step 3b), after the
  single approval gate.
- **Meeting-first sweep (Phase 2e) obeys AAA-only scope** — judge relevance by
  **content / attendees / project match, never the organizer or note-owner email** — surfaces
  1:1s in the routing loop (never auto-routes them), and **dedupes pages by `pageId`** so each
  canonical page is fetched and written exactly once even when multiple meetings and/or a project
  change target it.
- **Direct-report 1:1 trackers (Phase 2f/4b) are confidential and local-only** — the three trackers
  live under `_Documents\my Team\Team Yerelian\`; each is a JSON source + rendered `.docx`
  (`agenda-creator`'s `create_agenda_docx.py`). Refresh only when that report's 1:1 is on the target
  day; edit the JSON then re-render. Never publish or link them to Confluence / any shared page, and
  never delegate the proposal to a subagent (read-only Granola extraction only).
- Use **ISO dates** in the payload; exact names for owners/people (e.g. `Mariyo`).
- One approval gate only: gather everything, propose once, then execute.
- **Per-meeting agenda direction is optional and captured once.** Gather Dan's per-meeting blurbs
  one at a time in Phase 2b, persist them in `meeting-directions.json` keyed by meeting instance,
  and **reuse across closes** so the same meeting is never re-prompted (`skip` is remembered →
  auto-draft). The store lives in the OneDrive Daily Plan folder (never `$env:TEMP`), is pruned of
  past meetings each run, and is written BOM-free via the `Write` tool — never
  `Set-Content -Encoding utf8`. Direction takes precedence over auto-pulled context and folds into
  the existing agenda JSON fields only — no renderer/schema change.
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
