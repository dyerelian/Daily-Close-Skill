# Daily Close Skill (`close-day`)

A reusable Codex skill for end-of-day close-out workflows. It is read-first and
proposal-gated: enabled modules gather evidence, the skill presents one consolidated proposal,
and writes happen only after approval and only when local config permits the target.

## Quick Start

Clone the repo and install it into your Codex skills folder:

```powershell
git clone <repo-url>
cd Daily-Close-Skill

$live = Join-Path $env:USERPROFILE '.codex\skills\close-day'
if (Test-Path $live) { Remove-Item $live -Recurse -Force }
New-Item -ItemType Junction -Path $live -Target (Get-Location).Path | Out-Null
```

Generate onboarding questions for Codex or another LLM:

```powershell
python scripts\onboard_close_day.py questions --out outputs\onboarding\codex-onboarding-prompt.md
```

Create a safe setup preview from the example answers:

```powershell
python scripts\onboard_close_day.py run --answers config\onboarding.answers.example.json --dry-run
python scripts\onboard_close_day.py validate --config outputs\onboarding\dry-run-daily-close.local.json
```

For a real setup, copy `config\onboarding.answers.example.json`, fill in the user's answers, then
run without `--dry-run`:

```powershell
Copy-Item config\onboarding.answers.example.json config\onboarding.answers.local.json
# Edit config\onboarding.answers.local.json with the user's module choices and paths.
python scripts\onboard_close_day.py run --answers config\onboarding.answers.local.json
python scripts\validate_config.py --config config\daily-close.local.json
```

Then invoke the skill from Codex with a prompt such as:

```text
Use $close-day to close my day.
```

## Layout

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Codex skill instructions and approval model. |
| `modules/*.json` | Selectable module manifests. |
| `config/daily-close.example.json` | Portable example config. |
| `config/daily-close.local.json` | Local user profile, ignored by git. |
| `scripts/validate_config.py` | Validates config and module manifests. |
| `scripts/list_modules.py` | Lists modules and enabled status. |
| `scripts/onboard_close_day.py` | Guided onboarding: questions, setup artifact creation, and readiness validation. |
| `scripts/generate_crm_workbook.py` | Builds the CRM `.xlsx` template and CSV seed files. |
| `scripts/propose_crm_from_gmail.py` | Turns Gmail search/read JSON into CRM proposal JSON. |
| `assets/crm/` | Generated CRM workbook template and CSV seed headers/lists. |

The original Outlook, Teams, and Daily Plan scripts remain bundled under `scripts/`.

## Modules

Current manifests:

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

## Validate

```powershell
python scripts\validate_config.py --config config\daily-close.example.json
python scripts\list_modules.py --config config\daily-close.example.json
$quick = Join-Path $env:USERPROFILE '.codex\skills\.system\skill-creator\scripts\quick_validate.py'
python $quick .
```

## Onboarding

Generate the Codex/LLM question prompt and answer schema:

```powershell
python scripts\onboard_close_day.py questions --out outputs\onboarding\codex-onboarding-prompt.md
```

Run a safe local setup preview from the example answers:

```powershell
python scripts\onboard_close_day.py run --answers config\onboarding.answers.example.json --dry-run
python scripts\onboard_close_day.py validate --config outputs\onboarding\dry-run-daily-close.local.json
```

The wizard creates local config/templates and reports. Live Google Sheets, Google Docs, or
Confluence creation remains connector-backed and approval-gated.

## CRM Seed

Generate the local Google-Sheets-compatible CRM workbook and CSV seed files:

```powershell
python scripts\generate_crm_workbook.py --output assets\crm\daily-close-crm-template.xlsx --csv-dir assets\crm\csv_seed
```

Generate a dry-run CRM proposal from Gmail-shaped JSON:

```powershell
python scripts\propose_crm_from_gmail.py --input tests\fixtures\gmail_crm_seed_sample.json --out outputs\crm-proposals\sample-proposal.json --dry-run
```

Live Google Sheets writes are intentionally not implemented in v1. Use the generated workbook or
CSV seed first; native Sheets import or update requires a Drive/Sheets integration and explicit
approval.

## Install Locally

Use a junction so the installed Codex skill points at this repository:

```powershell
$live = Join-Path $env:USERPROFILE '.codex\skills\close-day'
$repo = (Get-Location).Path
if (Test-Path $live) { Remove-Item $live -Recurse -Force }
New-Item -ItemType Junction -Path $live -Target $repo | Out-Null
```

## Future Enhancements

These are not required for the current v1 flow, but they should be considered before the next
public onboarding pass.

- **Cleaner first-run instructions.** The current README assumes the user already has Codex
  installed, understands what a skill is, has a local skills folder, and is comfortable creating a
  junction manually. A future update should add a true "from zero" setup path with prerequisites,
  expected folder locations, Windows/macOS/Linux variants, and a bootstrap script that creates
  missing folders, checks Python/Git availability, installs the skill, and then runs validation.
- **LLM-model-agnostic onboarding.** The onboarding wizard should not be Codex-specific. It should
  keep the prompt/answer schema portable and support OpenAI/Codex, Claude, Gemini, Grok, and local
  LLMs through a provider-neutral flow. A future version could expose `questions`, `run`, and
  `validate` as the stable contract, then add provider adapters for CLI, API, or local endpoint
  use without changing module manifests.
- **AI-suggested: outcome-based module selection.** Instead of asking users to pick modules from a
  technical list first, the wizard should start with user outcomes such as "capture tasks",
  "summarize meetings", "update CRM", or "prepare tomorrow's plan." It can then recommend modules,
  show the required data sources, and let the user accept or remove each recommendation.
- **AI-suggested: onboarding readiness report with permission review.** After setup, the wizard
  should generate a plain-English readiness report that lists enabled modules, missing connectors,
  files created, read permissions, write targets, and rollback/uninstall steps. This gives users a
  final security and privacy checkpoint before any daily close-out run.
