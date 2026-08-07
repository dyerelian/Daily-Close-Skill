# close-day

`close-day` is a proposal-first Codex skill for personal, organization, and multi-organization
end-of-day reviews. It gathers configured sources read-only, labels every item by scope, pauses for
unclassified items, and asks for approval before local or external writes.

## What v2 adds

- Named profiles containing personal and/or organization scopes.
- Private configuration outside the Git repository.
- Google and Microsoft mail/calendar provider adapters, plus optional Slack, Teams, Granola,
  Atlassian, CRM, and source-of-truth modules.
- A user-selected workspace root with derived `Plans`, `Agendas`, `Tasks`, `Logs`, and `State`.
- Canonical Markdown/JSON artifacts with optional DOCX/XLSX exports.
- Optional Daily Takeaways, recurring-meeting recaps, and DOCX page numbers.
- Cross-platform installation, onboarding, migration, routing, and validation scripts.

## Install and onboard

Check the environment and preview installation:

```powershell
python scripts/install_close_day.py check
python scripts/install_close_day.py install --dry-run
```

Install and enter the first-run wizard:

```powershell
python scripts/install_close_day.py install
```

For a conversational setup, generate the question/answer contract, fill a private answer file, and
preview before applying:

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

## Development checks

```powershell
python -m unittest discover -s tests -p "test_*.py"
python scripts/validate_config.py --config config/daily-close.example.json
python scripts/onboard_close_day.py run --answers config/onboarding.answers.example.json --dry-run
python path/to/skill-creator/scripts/quick_validate.py .
git diff --check
```
