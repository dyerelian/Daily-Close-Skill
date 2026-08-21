# Configuration reference

## Contents

1. Registry and profiles
2. Required profile sections
3. Scope routing
4. Artifact layout
5. Migration and readiness

## Registry and profiles

Store private configuration outside the skill repository. Resolve the root from
`CLOSE_DAY_CONFIG_HOME`, then the operating-system default. Keep `registry.json` at the root and
profile JSON files under `profiles/`. The registry contains `schema_version`,
`default_profile_id`, and profile records with `id`, `name`, and `path`.

Use schema version 2. Give every profile a stable lowercase hyphenated id. A profile may contain a
personal scope, one organization scope, or several labeled scopes. Never combine separate profiles
without an explicit user request.

## Required profile sections

- `profile`: id and display name.
- `owner`: name, primary email when available, and IANA timezone.
- `schedule`: workdays and close-out time.
- `scopes`: classification and source-binding rules.
- `routing`: `pause_and_ask` unclassified policy and global exclusions.
- `artifacts`: workspace root, optional path overrides, canonical formats, and exports.
- `features`: Daily Takeaways, exact reflection requirements, recurring recaps, and DOCX page numbers.
- `privacy` and `permissions`: data retention and narrow write gates, including separate GTD,
  Jira, CRM, and email-delivery permissions.
- `enabled_modules` and `modules`: provider and capability configuration.

For `jira-sweep`, configure one or more objects containing `name`, `jql`, `scope_id`, and `limit`.
Optional lifecycle writes live under `jira-sweep.writes`: enable them only with scope-bound project
keys, issue types, allowed operations, mandatory duplicate checks, and
`permissions.jira_writes_enabled=true`.

`action-routing` declares the configured primary destinations, per-action-kind routing rules, and
fixes the overlap policy to `primary_with_links`. `gtd-google-sheet` stores the native sheet id or URL, connector readiness,
scope ids, scope-to-Area values, active/archive tab names, optional project tabs, and the required
archive-before-clear rule. Enable its `allow_writes` only with
`permissions.gtd_writes_enabled=true`. See [action-routing.md](action-routing.md) and
[gtd-google-sheet.md](gtd-google-sheet.md).

For `local-files`, configure approved roots containing `path`, `scope_id`, `recursive`,
`lookback_days`, and optional `include_extensions`. Bound large-drive traversal with `max_files`,
`max_scanned_files`, `max_scanned_directories`, and `max_scan_seconds`. Keep each query and root
bound to one scope.

## Scope routing

Each scope declares:

- `id`, `type` (`personal` or `organization`), and `name`
- `source_bindings` for exact account, calendar, workspace, or channel associations
- `domains` for participant/email classification
- `aliases` and `include_terms` for project/account matching
- `exclude_terms` for scope-local omissions

Classify by explicit scope, source binding, domain, then alias/term. Assign unmatched evidence to the
only scope only when the profile has exactly one. In a multi-scope profile, pause on every ambiguous
or unmatched item and obtain an explicit assignment, exclusion, or ignore decision.

Global exclusions use objects with `name`, non-empty `match_terms`, and optional `reason`. Apply them
before scope routing. Keep user-specific exclusions only in private profiles.

## Artifact layout

Derive `Plans`, `Agendas`, `Tasks`, `Logs`, and `State` from `artifacts.workspace_root`. Allow any of
those names to be replaced through `path_overrides`. Keep Markdown and JSON enabled as canonical
formats. Configure `daily_plan_docx`, `agenda_docx`, and `xlsx` independently. For compatibility,
legacy `docx` applies to both DOCX exports unless a granular flag is present.

Configure Daily Takeaways with `max_items`, optional `required_items`, and `incomplete_policy`.
`ask_until_complete` blocks finalization until both reflection lists contain the exact required
count; `allow_partial` retains the prior non-padding behavior.

Email delivery is an optional Gmail runtime-connector module. Configure `from`, `recipients`,
`mode`, `subject_template`, `body_style`, and attachments. Enable
`permissions.email_delivery_enabled` separately from general external writes. Store delivery
status, deterministic key, approved delivery key, approval time, attempt count, and categorized
failure in close state, but never OAuth data or Gmail identifiers. The deterministic identity
includes the profile, target date, sender, recipients, subject, body, attachments, and mode; any
change requires a new consolidated close approval.

CRM supports two modes. `portable_workbook` retains the generated Accounts/Contacts/Interactions/
FollowUps/Lists workbook. `delegated_handler` connects an existing CRM through `handler_skill` and
explicit `scope_ids`; configure `review_mode=incremental_daily`, first-run lookback, overlap hours,
new-row policy, minimum confidence, live-write permission, and `roll_weekly_jira=false`. Enable
`permissions.crm_writes_enabled` only when exact approved live writes are allowed. Keep private CRM
URLs and organization ids in private profile or handler configuration. Completed review watermarks
and deterministic change ids belong in close state, not full provider content or sheet snapshots.

## Migration and readiness

Preview schema-v1 migration before writing. Map old topic exclusions to global exclusions, translate
Gmail/Outlook sources into generic mail/calendar providers, and retain optional modules. Do not
delete or overwrite the legacy file. Require schema validation before making the new profile the
default.

Report `ready` when the profile, paths, and connectors are available; `usable_with_gaps` when an
optional path or connector is unavailable; and `blocked` for schema, routing, or safety failures.
