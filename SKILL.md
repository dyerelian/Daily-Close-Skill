---
name: close-day
description: Run and onboard a modular end-of-day close-out workflow with selectable modules for GTD review, Outlook/Teams/Gmail/Slack/Granola/Atlassian sweeps, daily planning, source-of-truth updates, and a Google-Sheets-compatible CRM. Use when the user says close my day, end of day, EOD, wrap up the day, daily review, plan tomorrow, install or configure close-day modules, run the onboarding wizard, include CRM follow-ups, create a CRM seed from email, or run a read-first proposal gate before GTD/CRM/document/Confluence writes.
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

- source coverage and any skipped modules
- items to mark complete or carry forward
- new captures and waiting-for items
- tomorrow or next-workday plan
- CRM account/contact/interaction/follow-up proposals when CRM is enabled
- Confluence/source-of-truth changes when enabled
- document or workbook artifacts that would be generated

Wait for explicit approval. After approval, execute only approved lines. If the user edits the
proposal, treat the edited proposal as the executable scope.

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
- Gmail-driven CRM updates are proposals, not silent writes.
- Google Sheets live writes are gated on an available connector or explicit integration path.
- Keep source evidence compact: message IDs, thread IDs, subject, date, sender, snippet, and link.
- Prefer deterministic scripts in `scripts/` for validation and repeatable artifacts.
