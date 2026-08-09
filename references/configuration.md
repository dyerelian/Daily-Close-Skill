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
- `features`: Daily Takeaways, recurring recaps, and DOCX page numbers.
- `privacy` and `permissions`: data retention and write gates.
- `enabled_modules` and `modules`: provider and capability configuration.

For `jira-sweep`, configure one or more objects containing `name`, `jql`, `scope_id`, and `limit`.
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
formats. Treat DOCX and XLSX as optional exports.

## Migration and readiness

Preview schema-v1 migration before writing. Map old topic exclusions to global exclusions, translate
Gmail/Outlook sources into generic mail/calendar providers, and retain optional modules. Do not
delete or overwrite the legacy file. Require schema validation before making the new profile the
default.

Report `ready` when the profile, paths, and connectors are available; `usable_with_gaps` when an
optional path or connector is unavailable; and `blocked` for schema, routing, or safety failures.
