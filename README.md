# close-day

`close-day` is a proposal-first Codex skill for personal, organization, and multi-organization
end-of-day reviews. It gathers configured sources read-only, labels every item by scope, pauses for
unclassified items, and asks for approval before local or external writes.

## What v2 adds

- Named profiles containing personal and/or organization scopes.
- Private configuration outside the Git repository.
- Google and Microsoft mail/calendar provider adapters, plus optional Slack, Teams, Granola,
  scoped Jira, scoped local-file, Atlassian, CRM, and source-of-truth modules.
- A user-selected workspace root with derived `Plans`, `Agendas`, `Tasks`, `Logs`, and `State`.
- Canonical Markdown/JSON artifacts with independent Daily Plan DOCX, agenda DOCX, and XLSX exports.
- Optional exact-count Daily Plan reflections, recurring-meeting recaps, DOCX page numbers, and
  one-close-approval Gmail delivery of the finalized plan with durable, duplicate-safe retries.
- Portable CRM workbooks or scope-bound incremental CRM review through a configured handler skill,
  with deterministic proposals and verified writes under the consolidated close approval.
- Cross-platform installation, onboarding, migration, routing, and validation scripts.

## Quick start: tell your LLM

Give the following instruction to a terminal-capable LLM agent. The agent should handle installation
and start setup; the user should not need to clone the repository or run Python commands.

> Install and configure the `close-day` agent skill from
> `https://github.com/dyerelian/Daily-Close-Skill` using the `main` branch. The skill is located at
> the repository root and must be installed under the name `close-day`. Use your environment's
> native skill installer when available; otherwise handle downloading and placement in the
> appropriate skills directory yourself. Do not ask me to clone the repository or run Python
> commands. If `close-day` already exists, inspect it and ask before replacing it. After
> installation, read the installed `SKILL.md` and begin first-time onboarding conversationally.
> Show me the proposed profile, scopes, folders, permissions, exclusions, enabled modules, and
> connector gaps before creating configuration or folders, and wait for my explicit approval.
> During the wizard, ask separately about the workspace root, Daily Plan DOCX, agenda DOCX, the
> required count and incomplete-answer policy for yesterday/today reflections, and finalized-plan
> email delivery (sender, recipients, send versus draft, subject, body style, attachment, and the
> narrowest available Gmail send-action permission). If CRM review is requested, ask whether to
> create a portable workbook or use an existing handler skill, which scopes it may receive, the
> first-run/overlap window, inference confidence, new-row policy, and live-write permission.

For Codex agents, the verified native installer arguments are:

```text
repo: dyerelian/Daily-Close-Skill
path: .
name: close-day
ref: main
```

The repository-root `path` and explicit `name` are important. A newly installed skill may not be
automatically discoverable until the next turn; the installing agent should read the installed
`SKILL.md` directly and continue onboarding in the current conversation.

## Manual and developer installation

These commands are a fallback for maintainers and environments without an agent-managed skill
installer. Check the environment and preview installation:

```powershell
python scripts/install_close_day.py check
python scripts/install_close_day.py install --dry-run
```

Install and enter the terminal-based first-run wizard:

```powershell
python scripts/install_close_day.py install
```

For an agent-managed conversational setup, the agent generates the question/answer contract,
collects answers in conversation, stores them in a private temporary answer file, and previews the
profile before applying it:

```powershell
python scripts/onboard_close_day.py questions
python scripts/onboard_close_day.py run --answers config/onboarding.answers.example.json --dry-run
python scripts/onboard_close_day.py run --answers path/to/private-answers.json --make-default --approved
```

Private profiles are stored under the operating-system configuration directory. Override it with
`CLOSE_DAY_CONFIG_HOME` when needed.

## Migrate a v1 setup

Migration retains the legacy file and preserves paths, enabled modules, permissions, and topic
exclusions:

```powershell
python scripts/onboard_close_day.py migrate --from config/daily-close.local.json --dry-run
python scripts/onboard_close_day.py migrate --from config/daily-close.local.json --make-default --approved
```

## Validate and inspect

```powershell
python scripts/validate_config.py --config config/daily-close.example.json
python scripts/onboard_close_day.py profiles list
python scripts/onboard_close_day.py validate --profile my-close
python scripts/list_modules.py --profile my-close
```

Read `references/configuration.md` for the profile schema and
`references/provider-adapters.md` for normalized evidence and connector behavior.

## Portable artifact flow

Route normalized evidence before proposing the close:

```powershell
python scripts/route_close_items.py --input evidence.json --profile my-close --output routed.json
```

Exit code `2` means unclassified items require an explicit user decision. After the consolidated
proposal is approved, preview and create artifacts:

```powershell
python scripts/create_close_artifacts.py --input approved-close.json --profile my-close --dry-run
python scripts/create_close_artifacts.py --input approved-close.json --profile my-close --approved
```

Existing dated artifacts are not overwritten. OAuth credentials are never stored in this project,
and external writes remain separately proposal-gated.

For an existing CRM, configure `crm-google-sheet` in `delegated_handler` mode. The close prepares a
scope-filtered incremental request, validates deterministic cell-level changes from the handler,
and includes them in the consolidated proposal. The handler re-reads affected rows before approved
writes and verifies them afterward; its standalone weekly Jira rollover remains disabled during a
daily close. See `references/crm-handler-contract.md`.

When configured, the finalized Daily Plan email is prepared only after DOCX render verification.
The agent shows its exact delivery details in the close proposal and records that delivery key as
approved. It then sends or drafts through the runtime Gmail connector without a second skill-level
approval. Matching interrupted or failed deliveries require an exact Sent-folder check before a
safe retry; matching successful deliveries are never repeated. Gmail identifiers are not stored.

Gmail's own app confirmation setting remains independent. Prefer an action-specific exception when
available; do not set the whole Gmail plugin to `Never ask` solely for close-day. See
`references/gmail-delivery.md` for managed-workspace constraints, Google scope setup, and the
diagnostic for an unexpected required `payload` field.

## Future improvements

These are backlog notes only and are not implemented:

- **Canonical sources of truth:** Add a proposal-gated integration that can create or update a
  configured project's canonical source-of-truth page or record.
- **Daily Success agenda items:** Add opt-in, per-profile routines such as journaling, working out,
  and medication to the daily agenda, with configurable schedules and completion tracking.

## Development checks

```powershell
python -m unittest discover -s tests -p "test_*.py"
python scripts/validate_config.py --config config/daily-close.example.json
python scripts/onboard_close_day.py run --answers config/onboarding.answers.example.json --dry-run
python path/to/skill-creator/scripts/quick_validate.py .
git diff --check
```
