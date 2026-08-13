---
name: close-day
description: Run, install, onboard, migrate, or reconfigure a proposal-first end-of-day close for personal, organization, or multi-organization profiles. Use for close my day, EOD, daily review, plan tomorrow, meeting agendas, task capture, Daily Takeaways, recurring-meeting recaps, CRM/source-of-truth follow-ups, or setup of local close-day folders, scoped file roots, Jira, Google/Microsoft sources, modules, profiles, and write permissions.
---

# close-day

Run a read-first, proposal-first close. Keep personal and organization data labeled by configured
scope. Never perform an external write or create a local artifact before the applicable approval.

## Install requests

When asked to install from GitHub, handle the installation for the user. Do not ask the user to
clone the repository or run Python commands.

1. Prefer the environment's native skill installer. Install `dyerelian/Daily-Close-Skill` from
   `main`, using repository path `.` and installation name `close-day`.
2. If no native installer exists, download or clone the repository into the environment's standard
   skills directory under `close-day`.
3. If the destination already exists, inspect it and ask before replacing it. Never silently
   overwrite an installed skill or its private configuration.
4. After installation, read the installed `SKILL.md` directly and continue with first-run setup in
   the current conversation. If skill discovery refreshes only between turns, explain that future
   requests will discover it on the next turn; do not defer onboarding solely for that reason.

## Start and first run

1. Resolve this skill directory; use the current folder or `~/.codex/skills/close-day`.
2. Run `python scripts/onboard_close_day.py profiles list`.
3. If no schema-v2 profile exists, start onboarding:
   - For a new user, run `python scripts/onboard_close_day.py questions` and gather the answers
     conversationally. Preview with `run --answers <answers.json> --dry-run`, show paths,
     permissions, and gaps, then run with `--approved` only after confirmation.
   - If `config/daily-close.local.json` exists, preview `migrate --from
     config/daily-close.local.json --dry-run`. Preserve the legacy file and apply a migration only
     after the user reviews its profile name, scopes, paths, exclusions, and permissions; require
     `--approved` for the applied migration.
4. Select an explicitly named profile or the registry default. If neither resolves, ask which
   profile to use; do not combine profiles implicitly.
5. Run `python scripts/onboard_close_day.py validate --profile <id>` and
   `python scripts/list_modules.py --profile <id>`. Report missing paths/connectors as coverage
   gaps and ask whether to continue with available sources. Never silently skip an enabled source.

Read [configuration.md](references/configuration.md) when onboarding, migrating, editing a profile,
or resolving classification. Read [provider-adapters.md](references/provider-adapters.md) when
using Google, Microsoft, Slack, Teams, Granola, Jira, or Confluence sources.
Read [gmail-delivery.md](references/gmail-delivery.md) when enabling or troubleshooting Daily Plan
email delivery.

## Gather and route

1. Read only enabled module sources and normalize each candidate to the evidence contract in
   `references/provider-adapters.md`.
   - For `jira-sweep`, execute only configured JQL and stamp every result with that query's
     `scope_id` before routing.
   - For `local-files`, run `python scripts/collect_local_files.py --profile <id>`. Route the
     emitted metadata first; read file contents only for shortlisted items inside the configured
     root and scope.
2. Apply global and scope exclusions before analysis. Inspect excluded material only far enough to
   recognize it, then omit it from proposals, plans, CRM, Jira, source-of-truth updates, and
   artifacts. Allow a one-run exception only when the user explicitly names the excluded topic.
3. Route evidence using `python scripts/route_close_items.py --input <evidence.json> --profile
   <id> --output <routed.json>`.
4. Label every included item with its `scope_id`. Present a combined prioritized close using the
   profile's scope display names.
5. If routing returns any unclassified items, pause. Show the complete list and ask the user to
   assign, exclude, or ignore every item. Do not build the consolidated proposal until the list is
   resolved.

## Build the close

Review task state, communication, meetings, and source-of-truth evidence. Ask only about unresolved
planned priorities that evidence cannot settle, manual captures, and next-workday priorities.

When Daily Takeaways are enabled, draft concrete things done well and improvements. If
`required_items` is nonzero and `incomplete_policy` is `ask_until_complete`, obtain exactly that
many evidence-backed items in both lists before finalization. Never invent or pad an item. Put the
two reflection lists immediately after the Daily Plan title, before its summary.

For a recurring meeting, build **Last meeting recap** within the same scope. Match provider event
identity first, then normalized title, participants, and start time. Prefer the prior Granola note
when enabled; fall back to the prior local agenda or state. Include summary, unresolved follow-ups
with owners, decisions, and suggested talking points. State `No prior meeting found.` when needed.

## Approval gates

Present one consolidated proposal containing:

- proposed Jira tickets first, when any exist
- source coverage, gaps, and ignored or excluded material counts
- completed, carried, captured, waiting-for, and task updates with scope labels
- Daily Takeaways and next-workday priorities
- meeting recaps and agendas
- CRM and source-of-truth proposals
- every local artifact or external write that would occur
- the exact email sender, recipients, subject, body style, and attachments when email delivery is enabled

For each proposed Jira ticket, show exact summary, project, issue type, assignee, due date or `none`,
parent/related issue, concise acceptance criteria, and duplicate-search result. Require explicit
approval of that displayed Jira list; general approval does not authorize an undisclosed ticket.

Wait for explicit approval. Treat user edits as the executable scope and execute only approved
lines. Run writes in this order: tasks, CRM, source-of-truth, logs/state, plans, and agendas.

## Artifacts

Use Markdown and JSON as canonical artifacts. Preview with:

```powershell
python scripts/create_close_artifacts.py --input <approved-close.json> --profile <id> --dry-run
```

After artifact approval and only when the profile permits local writes, rerun with `--approved`.
The script refuses to overwrite an existing dated artifact. Generate Daily Plan DOCX, agenda DOCX,
or XLSX task exports only when each export is enabled. Treat legacy `artifacts.exports.docx=true` as
enabling both DOCX types unless a granular flag overrides it. Pass approved Takeaways to the Daily
Plan renderer and use its configurable page-number footer.

When `email-delivery` is enabled, prepare the deterministic envelope with
`scripts/prepare_close_email.py` only after the approved artifacts exist and the Daily Plan DOCX has
passed render review. Record `approved` for the displayed email covered by the consolidated close
approval, prepare again, then record `pending` immediately before sending or drafting through the
runtime Gmail connector. Record `sent` or categorized `failed` afterward. Never store OAuth
credentials or Gmail message/thread identifiers.

Treat a matching `approved_delivery_key` as durable authorization for that exact sender,
recipients, subject, body, attachment set, mode, and target date. Do not ask for another skill-level
approval when resuming that delivery. Before resuming a matching `pending` or `failed` delivery,
search Gmail Sent for the exact recipient and subject. Record `sent` without resending when found;
when absent, prepare with `--sent-check-absent` and send only if the resulting envelope is sendable.
Stop when the Sent check is unavailable or the provider outcome is ambiguous. A changed delivery
key requires inclusion in a new consolidated proposal. Never change the subject merely to bypass
duplicate protection.

When CRM is enabled, read [crm-google-sheet.md](references/crm-google-sheet.md). Keep mail-derived
CRM changes proposal-only. Generate local workbook/CSV output unless a live Sheets connector and
the approved profile both allow the exact write.

## Guardrails

- Keep private profiles and connector state outside the Git repository.
- Bind sources to allowed scopes before prioritizing; never leak evidence across profiles.
- Keep external systems read-only during gathering.
- Require the proposal gate for local and external writes and the stricter Jira gate for tickets.
- Never store OAuth credentials; connector authentication is runtime-managed.
- Keep source evidence compact: provider, stable id, account/workspace, timestamp, title, snippet,
  participants, and link.
- Use deterministic scripts for installation, onboarding, migration, routing, validation, and
  artifact generation.
