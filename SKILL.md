---
name: close-day
description: Run and onboard a modular end-of-day close-out workflow with selectable modules for GTD review, Outlook/Teams/Gmail/Slack/Granola/Atlassian sweeps, daily planning, source-of-truth updates, Jira ticket proposals, and a Google-Sheets-compatible CRM. Use when the user says close my day, end of day, EOD, wrap up the day, daily review, plan tomorrow, install or configure close-day modules, run the onboarding wizard, include CRM follow-ups, create a CRM seed from email, or run a read-first proposal gate before Jira/GTD/CRM/document/Confluence writes.
---

# close-day

Use this skill as a read-first, propose-then-confirm shutdown workflow. Load enabled modules,
gather read-only evidence, present one consolidated proposal, then execute writes only after the
user approves the proposal and the local config permits that write target.

## Start

1. Resolve the skill directory. Prefer the current skill folder; if needed, use
   `~/.codex/skills/close-day`.
2. Load `config/daily-close.local.json` when it exists. Otherwise load
   `config/daily-close.example.json` and treat all writes as disabled.
   When `scope_exclusions.topics` is present, apply every listed topic across all enabled
   modules. Match the topic name and `match_terms` case-insensitively as standalone terms or
   clear project/account references. Broad source sweeps may retrieve excluded material, but
   inspect it only far enough to distinguish it from in-scope work, then omit it from analysis,
   proposals, plans, CRM, Jira, source-of-truth updates, and generated artifacts. A user may
   override an exclusion for one run only by explicitly naming the excluded topic.
3. Run:
   `python scripts/validate_config.py --config <config-path>`
4. Run:
   `python scripts/list_modules.py --config <config-path>`
5. Use only enabled modules unless the user explicitly asks to add or remove modules for this run.

If validation reports missing connectors or paths, explain what coverage is lost and ask whether
to proceed with the available sources. Do not silently skip an enabled module.

## Onboarding

When the user asks to install, configure, onboard, choose modules, or set up reference files, use
the deterministic wizard before running a real close-out:

```powershell
python scripts/onboard_close_day.py questions --out outputs/onboarding/codex-onboarding-prompt.md
python scripts/onboard_close_day.py run --answers config/onboarding.answers.example.json --dry-run
python scripts/onboard_close_day.py validate --config outputs/onboarding/dry-run-daily-close.local.json
```

Workflow:

1. Use `questions` to generate the LLM/Codex question catalog and answer schema.
2. Ask the user the relevant questions, then save answers as JSON using
   `config/onboarding.answers.example.json` as the shape.
3. Run `run --answers <answers.json>` to create `daily-close.local.json`, local templates, and setup
   reports. Use `--dry-run` first for a safe preview.
4. Run `validate` and report setup status as `ready`, `usable_with_gaps`, or `blocked`.

The wizard creates local templates/config only. Native Google Sheets, Google Docs, or Confluence
creation remains a connector-backed follow-up and requires explicit approval.

## Module Model

Modules live in `modules/*.json`. Each manifest declares:

- `id`
- `display_name`
- `description`
- `required_connectors`
- `read_sources`
- `write_targets`
- `config_schema`
- `enabled_by_default`
- `proposal_output_type`

Use the module manifests as the source of truth for what a module may read and write. Write targets
are not permission by themselves; they are only eligible after the single approval gate and only
when `write_mode.enabled` is true in config.

## Approval Gate

Gather everything first, then show one consolidated proposal. The proposal should include:

- proposed new Jira tickets, listed first when any are candidates
- source coverage and any skipped modules
- items to mark complete or carry forward
- new captures and waiting-for items
- tomorrow or next-workday plan
- CRM account/contact/interaction/follow-up proposals when CRM is enabled
- Confluence/source-of-truth changes when enabled
- document or workbook artifacts that would be generated

Wait for explicit approval. After approval, execute only approved lines. If the user edits the
proposal, treat the edited proposal as the executable scope.

### Jira Ticket Creation Gate

Always put proposed new Jira tickets first in the consolidated proposal. Before proposing them,
search Jira read-only for duplicates or existing work that already covers the capture.

For each proposed ticket, list:

- exact summary
- project and issue type
- intended assignee
- due date, or `none` when no source-backed date exists
- parent or related issue, when applicable
- concise scope and acceptance criteria
- duplicate-search result

Do not create any Jira ticket until the user explicitly approves the displayed ticket list.
General approval of the rest of the close-day proposal does not approve Jira ticket creation when
the exact tickets were not listed. If the user approves only a subset or edits a ticket, create
only that final approved set. Never silently add another Jira ticket during execution.

## Close-Out Flow

1. Preflight connectors and local scripts for enabled modules.
2. Read current GTD state if `gtd-workbook` is enabled.
3. Sweep enabled communication and meeting modules read-only.
4. Ask how unresolved planned priorities landed when evidence does not settle them.
5. Ask for manual captures and next-day priorities.
6. Build the consolidated proposal.
7. After approval, execute allowed writes in this order:
   GTD workbook updates, CRM updates or local proposal export, source-of-truth updates,
   EOD log, Daily Plan document, standalone agendas.

## Agendas: recurring-meeting recap

When the `daily-plan-docx` module generates standalone or embedded agendas, open each
**recurring** meeting's agenda (1:1s, standing syncs) with a **Last meeting recap** built
from the previous instance of that same meeting:

1. Identify the meeting as recurring by matching its title/counterpart to a prior agenda or
   prior meeting note (normalized subject + start time).
2. Chain to the prior instance's agenda file in `paths.agenda_dir` (most recent dated agenda
   before this meeting whose title matches) and read it for last time's commitments,
   decisions, and open loops.
3. If the `granola-meetings` module is enabled, find that instance's Granola note
   (`search_notes`/`recent_notes`, correlate by start-time overlap + fuzzy title) and prefer
   it as the recap source; fall back to the prior agenda, then local notes.
4. Compose the recap with: a short summary of what was discussed, open follow-ups / action
   items (with owner where known), decisions made, and suggested talking points for this
   meeting. Carry unresolved follow-ups forward as this meeting's talking points so nothing
   is dropped. If no prior instance is found, state "No prior meeting found."

## CRM Module

When `crm-google-sheet` is enabled, read `references/crm-google-sheet.md` before proposing CRM
changes. The CRM workflow is always proposal-first:

1. Search Gmail with narrow, recent account/topic queries.
2. Save or pass Gmail search/read results to `scripts/propose_crm_from_gmail.py`.
3. Review the emitted proposal JSON.
4. Present account candidates, contact candidates, interaction summaries, follow-ups the owner
   owes, follow-ups others owe the owner, confidence, and source message/thread references.
5. Do not write to Google Sheets in v1. Generate a local `.xlsx`/CSV seed first with
   `scripts/generate_crm_workbook.py`. Native Google Sheets import or live updates require a
   connected Drive/Sheets integration and explicit approval.

Useful commands:

```powershell
python scripts/generate_crm_workbook.py --output assets/crm/daily-close-crm-template.xlsx --csv-dir assets/crm/csv_seed
python scripts/propose_crm_from_gmail.py --input tests/fixtures/gmail_crm_seed_sample.json --out outputs/crm-proposals/sample-proposal.json --dry-run
```

## Local Profile

User-specific paths, accounts, and enabled-module choices belong in
`config/daily-close.local.json`. This file is ignored from git. Keep write targets disabled in
local smoke tests unless the user explicitly approves a live close-out run.

Persistent topic exclusions also belong in the local profile:

```json
"scope_exclusions": {
  "match_mode": "case_insensitive_term",
  "topics": [
    {
      "name": "Example excluded project",
      "match_terms": ["EXAMPLE"],
      "reason": "User-requested exclusion"
    }
  ]
}
```

The base local profile may include these modules:

- `calendar-outlook`
- `sent-mail-outlook`
- `teams-local-cache`
- `gtd-workbook`
- `daily-plan-docx`
- `source-of-truth`
- `gmail-sweep`
- `granola-meetings`
- `slack-sweep`
- `crm-google-sheet`

## Guardrails

- Reads are allowed only from enabled module sources.
- External writes are never allowed during sweep/gather phases.
- Gmail, Slack, Granola, Teams, Outlook, Jira, and Confluence scans are read-only until approval.
- Jira ticket creation always requires the Jira-specific proposal list and explicit user approval.
- Gmail-driven CRM updates are proposals, not silent writes.
- Google Sheets live writes are gated on an available connector or explicit integration path.
- Keep source evidence compact: message IDs, thread IDs, subject, date, sender, snippet, and link.
- Prefer deterministic scripts in `scripts/` for validation and repeatable artifacts.
