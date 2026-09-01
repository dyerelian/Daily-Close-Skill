# Provider adapter reference

## Contents

1. Provider support
2. Normalized evidence contract
3. Source bindings and privacy
4. Failure behavior

## Provider support

Use connector-backed Gmail and Google Calendar adapters. Use connector-backed Outlook mail/calendar
on every platform, with bundled read-only Outlook COM scripts as a Windows fallback. Keep Slack,
Granola, Teams local cache, Jira, and Confluence optional. Never implement or store OAuth secrets in
this skill.

Bind every Jira JQL query to exactly one `scope_id`. Bind every approved local-file root to exactly
one `scope_id`; discover metadata with `scripts/collect_local_files.py` before reading any content.
Do not follow directory links or inspect files outside a configured root.

Treat the following provider-specific data as source metadata, not profile identity: message or
event ids, thread ids, calendar ids, account addresses, workspace/channel ids, timestamps, links,
and participant addresses.

## Normalized evidence contract

Normalize every gathered candidate before routing:

```json
{
  "id": "provider-stable-id",
  "kind": "message|meeting|task|note|issue|file|manual",
  "title": "Short title",
  "text": "Compact actionable summary",
  "participants": ["person@example.org"],
  "timestamp": "ISO-8601 timestamp",
  "source": {
    "provider": "gmail|google|google-sheets|outlook|slack|teams|granola|jira|confluence|local-files",
    "account": "configured account",
    "workspace": "optional workspace",
    "channel": "optional channel",
    "calendar": "optional calendar",
    "id": "provider-stable-id",
    "link": "optional deep link"
  }
}
```

Keep `text` compact. Do not copy full message bodies, transcripts, or pages unless the user permits
raw external content and the close genuinely needs it.

## Source bindings and privacy

Associate each configured provider/account/calendar/workspace/channel with allowed `scope_ids`.
Use exact source bindings before content-based rules. A source may feed several scopes, but every
individual item still requires a unique classification or an explicit user decision.

For Jira and local files, add the configured `scope_id` directly to every normalized item. Treat a
local path as source metadata, never as permission to search a parent or sibling directory.

Do not pass excluded material to downstream analysis. Do not reuse evidence from one profile while
running another profile.

## Failure behavior

Probe connectors during onboarding without requesting content. If a selected connector is missing,
report the module and provider as a coverage gap. Continue only after the user agrees to available
coverage. Never replace a missing Google or Microsoft source with an unrelated account or provider.

Treat `connector_configured` as an authentication declaration, not proof that Gmail write actions
work. Verify the write path on the first approved delivery. Classify connector schema errors that
require a `payload` field absent from the published Gmail action as `workspace_policy`; do not call
them duplicates or retry them in a loop. See [gmail-delivery.md](gmail-delivery.md).
