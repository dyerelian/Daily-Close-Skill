# GTD Google Sheet contract

Use this reference when `gtd-google-sheet` is enabled.

## Method

The workbook is the trusted master inventory for all configured, non-excluded commitments. Apply
the five-stage workflow every close:

1. **Capture** everything that has attention from enabled sources and a manual mind sweep. Apply
   exclusions before any workbook proposal. `Inbox` receives only material that cannot yet be
   clarified.
2. **Clarify** each item. If it is actionable, define the successful outcome when multi-step and
   one physical, visible, verb-led next action. If it is not actionable, route it to drop/trash,
   reference, Read/Review, Someday/Maybe, or a date-specific calendar/tickler.
3. **Organize** the reminder on Next Actions, Waiting Fors, a project list, the calendar, or an
   incubation/reference surface. Every active project must have at least one current Next Action,
   Waiting For, or calendar trigger.
4. **Reflect** by reconciling completions and changes, processing Inbox to zero, reviewing the past
   and upcoming calendar, reviewing follow-ups, and checking touched projects.
5. **Engage** by selecting a curated Daily Big 3 from the trusted system using the calendar's hard
   landscape, context, time available, work type/energy, and priority. Selection for today never
   creates a due date.

On the last configured workday, perform a Weekly Review: empty capture points and mind-sweep; review
all Next Actions, past/upcoming calendar, Waiting Fors, every active project and relevant support;
then review Someday/Maybe and Read/Review. Surface stalled projects and propose a new next action,
completion, or incubation. Carry a missed Weekly Review to the next close.

Actions estimated under two minutes appear in a Quick Wins review. Confirmed completions go
directly to the archive/log rather than becoming active rows; deferred quick wins follow normal
routing.

## Required lifecycle surfaces

The profile maps four logical tabs: `next_actions`, `waiting_fors`, `inbox`, and `archive`.
`Next Actions` and `Waiting Fors` own clarified active work. `Inbox` holds unclarified capture that
must be reviewed. `Action Archive` receives completed, cancelled, resolved, or dropped rows before
they are removed from an active tab. `archive_before_clear` must remain true.

Each active row must expose `Close Action ID`, source provider/id/link, external key, created time,
and last-sync time. These metadata columns may be hidden for usability. Scope-to-Area values and
per-scope project tabs are profile configuration, not hard-coded assumptions.

The default Next Actions headers are:

`Area | Related Project | Next Action | Context | Category | Defer / Review On | Due | Priority |
Status | Close Action ID | Source Provider | Source ID | Source Link | External Key | Created At |
Last Synced At`

Use the configured Context vocabulary. For Dan's current profile it is `@Computer`, `@Calls`,
`@Errands`, and `@Anywhere`. Keep Category as work type. `Due` is only an evidence-backed external
deadline; `Defer / Review On` is a tickler, availability date, or chosen review prompt. A stale date
is moved to Defer/Review unless source evidence proves a real deadline; preserve or correct that
deadline in Due.

Project rows state the desired outcome. `Next Action Summary` mirrors one current action and must
not contain a checklist or multiple future steps. A project can have multiple parallel next
actions in the action list, but each row still represents one physical action.

For Jira-managed work, GTD remains the master personal reminder and the Jira issue is the linked
detailed execution record. Store the Jira key/URL in source fields. When one next action is
completed, archive it and capture the next physical action if the project remains active.

## Safe write sequence

Before proposing changes, read spreadsheet metadata, required header rows, and candidate rows.
Run `scripts/gtd_sheet_contract.py audit` against the observed headers. Build operations only from
approved primary GTD actions, then validate them under both `allow_writes` and
`permissions.gtd_writes_enabled`.

For an upsert, search `Close Action ID` first. Update the matched row or append once when no match
exists. For completion, append the archive record, verify it, then clear the active row. Never
clear an active row if the archive write or verification failed. Re-read affected rows immediately
before a write and verify the exact cells afterward.

Stale dates are review signals, not evidence of completion. Preserve stale items until the user
explicitly completes, cancels, resolves, or drops them.
