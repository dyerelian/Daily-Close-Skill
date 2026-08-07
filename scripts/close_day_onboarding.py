#!/usr/bin/env python3
"""Deterministic schema-v2 onboarding implementation for close-day."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from close_day_config import (
    SCHEMA_VERSION,
    atomic_write_json,
    atomic_write_text,
    default_config_root,
    load_json,
    load_registry,
    migrate_v1_profile,
    profile_path,
    register_profile,
    registry_path,
    resolve_profile,
    resolved_artifact_paths,
    slugify,
    validate_profile,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "modules"
DEFAULT_REPORT_DIR = ROOT / "outputs" / "onboarding"


def default_answers() -> dict:
    return load_json(ROOT / "config" / "onboarding.answers.example.json")


def load_manifests() -> dict[str, dict]:
    result = {}
    for path in sorted(MODULE_DIR.glob("*.json")):
        manifest = load_json(path)
        result[manifest["id"]] = manifest
    return result


def ask(prompt: str, default: str = "") -> str:
    value = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return value or default


def yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "true", "1"}


def collect_interactive_answers() -> dict:
    answers = default_answers()
    profile = answers["profile"]
    owner = answers["owner"]
    profile["name"] = ask("Profile name", profile["name"])
    profile["id"] = slugify(ask("Profile id", profile["id"]))
    owner["name"] = ask("Your name", owner["name"])
    owner["primary_email"] = ask("Primary email", owner.get("primary_email") or "") or None
    owner["timezone"] = ask("Timezone", owner["timezone"])
    answers["artifacts"]["workspace_root"] = ask(
        "Workspace root", answers["artifacts"]["workspace_root"]
    )

    scope_name = ask("First scope name", "Personal")
    scope_type = ask("Scope type (personal/organization)", "personal").lower()
    aliases = [value.strip() for value in ask("Scope aliases (comma-separated)").split(",") if value.strip()]
    domains = [value.strip() for value in ask("Scope email domains (comma-separated)").split(",") if value.strip()]
    bindings = [value.strip() for value in ask("Scope source bindings (comma-separated)").split(",") if value.strip()]
    answers["scopes"] = [{
        "id": slugify(scope_name, "personal"),
        "type": scope_type,
        "name": scope_name,
        "aliases": aliases,
        "domains": domains,
        "include_terms": [],
        "exclude_terms": [],
        "source_bindings": bindings,
    }]
    while yes_no("Add another organization or personal scope?", False):
        scope_name = ask("Scope name")
        scope_type = ask("Scope type (personal/organization)", "organization").lower()
        aliases = [value.strip() for value in ask("Aliases (comma-separated)").split(",") if value.strip()]
        domains = [value.strip() for value in ask("Email domains (comma-separated)").split(",") if value.strip()]
        bindings = [value.strip() for value in ask("Source bindings (comma-separated)").split(",") if value.strip()]
        answers["scopes"].append({
            "id": slugify(scope_name),
            "type": scope_type,
            "name": scope_name,
            "aliases": aliases,
            "domains": domains,
            "include_terms": [],
            "exclude_terms": [],
            "source_bindings": bindings,
        })

    mail = ask("Mail providers (gmail/outlook/both/none)", "gmail").lower()
    calendar = ask("Calendar providers (google/outlook/both/none)", "google").lower()
    scope_ids = [scope["id"] for scope in answers["scopes"]]
    answers["systems"]["mail"]["providers"] = []
    if mail in {"gmail", "both"}:
        answers["systems"]["mail"]["providers"].append({
            "provider": "gmail", "account": owner.get("primary_email"), "connector": "gmail",
            "configured": False, "scope_ids": scope_ids,
        })
    if mail in {"outlook", "both"}:
        answers["systems"]["mail"]["providers"].append({
            "provider": "outlook", "adapter": "outlook-com" if platform.system() == "Windows" else "connector",
            "configured": False, "scope_ids": scope_ids,
        })
    answers["systems"]["calendar"]["providers"] = []
    if calendar in {"google", "both"}:
        answers["systems"]["calendar"]["providers"].append({
            "provider": "google", "connector": "google-calendar", "configured": False, "scope_ids": scope_ids,
        })
    if calendar in {"outlook", "both"}:
        answers["systems"]["calendar"]["providers"].append({
            "provider": "outlook", "adapter": "outlook-com" if platform.system() == "Windows" else "connector",
            "configured": False, "scope_ids": scope_ids,
        })

    excluded = [value.strip() for value in ask("Globally excluded topics (comma-separated)").split(",") if value.strip()]
    answers["routing"]["global_exclusions"] = [
        {"name": value, "match_terms": [value], "reason": "User-requested during onboarding"}
        for value in excluded
    ]
    answers["permissions"]["local_artifact_writes_enabled"] = yes_no(
        "Allow local artifact creation after approval?", True
    )
    answers["artifacts"]["exports"]["docx"] = yes_no("Export DOCX plans and agendas?", False)
    answers["artifacts"]["exports"]["xlsx"] = yes_no("Export XLSX task workbooks?", False)
    if yes_no("Override any derived Plans/Agendas/Tasks/Logs/State folders?", False):
        for key in ("plans", "agendas", "tasks", "logs", "state"):
            value = ask(f"{key.title()} folder override (leave blank for derived default)")
            if value:
                answers["artifacts"]["path_overrides"][key] = value
    return answers


def build_profile(answers: dict) -> dict:
    profile_answers = answers.get("profile") or {}
    owner = answers.get("owner") or {}
    scopes = answers.get("scopes") or []
    artifacts = answers.get("artifacts") or {}
    systems = answers.get("systems") or {}
    features = answers.get("features") or {}
    permissions = answers.get("permissions") or {}

    enabled = ["task-store", "daily-artifacts"]
    modules: dict[str, dict] = {
        "task-store": {
            "enabled": True,
            "provider": (systems.get("tasks") or {}).get("provider") or "portable",
            "existing_path": (systems.get("tasks") or {}).get("existing_path"),
            "allow_writes": bool((systems.get("tasks") or {}).get("allow_writes_after_approval")),
        },
        "daily-artifacts": {"enabled": True},
    }
    mail = systems.get("mail") or {}
    if mail.get("providers"):
        enabled.append("mail-sweep")
        modules["mail-sweep"] = {"enabled": True, "providers": mail["providers"], "window": mail.get("window", "7d")}
    calendar = systems.get("calendar") or {}
    if calendar.get("providers"):
        enabled.append("calendar-sweep")
        modules["calendar-sweep"] = {
            "enabled": True,
            "providers": calendar["providers"],
            "days_ahead": int(calendar.get("days_ahead") or 1),
        }
    optional = systems.get("optional_modules") or {}
    for module_id in ("granola-meetings", "slack-sweep", "teams-local-cache", "source-of-truth", "crm-google-sheet"):
        value = dict(optional.get(module_id) or {})
        if value.get("enabled"):
            workspace = Path(artifacts.get("workspace_root") or Path.home() / "Documents" / "close-day").expanduser()
            if module_id == "crm-google-sheet":
                value.setdefault("workbook_path", str(workspace / "CRM" / "close-day-crm.xlsx"))
                value.setdefault("proposal_output_dir", str(workspace / "CRM" / "proposals"))
                value.setdefault("csv_seed_dir", str(workspace / "CRM" / "csv_seed"))
                value.setdefault("allow_live_sheet_writes", False)
            if module_id == "source-of-truth":
                value.setdefault("mode", "local_files")
                value.setdefault("allow_confluence_writes", False)
                value.setdefault("mapping_path", str(workspace / "Source of Truth" / "source-of-truth-map.csv"))
            enabled.append(module_id)
            modules[module_id] = value

    personal_or_mixed = any(scope.get("type") == "personal" for scope in scopes)
    takeaway = features.get("daily_takeaways") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "profile": {
            "id": slugify(profile_answers.get("id") or profile_answers.get("name") or "default"),
            "name": profile_answers.get("name") or "Default Close",
        },
        "owner": {
            "name": owner.get("name") or "Close-day User",
            "primary_email": owner.get("primary_email"),
            "timezone": owner.get("timezone") or "UTC",
        },
        "schedule": answers.get("schedule") or {
            "workdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "close_out_time": "17:00",
        },
        "scopes": scopes,
        "routing": {
            "unclassified_policy": "pause_and_ask",
            "global_exclusions": (answers.get("routing") or {}).get("global_exclusions") or [],
        },
        "artifacts": {
            "workspace_root": artifacts.get("workspace_root") or str(Path.home() / "Documents" / "close-day"),
            "path_overrides": artifacts.get("path_overrides") or {},
            "canonical": {"markdown": True, "json": True},
            "exports": {
                "docx": bool((artifacts.get("exports") or {}).get("docx")),
                "xlsx": bool((artifacts.get("exports") or {}).get("xlsx")),
            },
        },
        "features": {
            "daily_takeaways": {
                "enabled": bool(takeaway.get("enabled", personal_or_mixed)),
                "max_items": int(takeaway.get("max_items") or 3),
            },
            "recurring_meeting_recap": {
                "enabled": bool((features.get("recurring_meeting_recap") or {}).get("enabled", True))
            },
            "docx_page_numbers": bool(features.get("docx_page_numbers", True)),
        },
        "privacy": answers.get("privacy") or {"allow_raw_external_content": False},
        "permissions": {
            "proposal_required": True,
            "external_writes_enabled": bool(permissions.get("external_writes_enabled")),
            "local_artifact_writes_enabled": bool(permissions.get("local_artifact_writes_enabled")),
            "jira_ticket_approval_required": True,
            "crm_writes_enabled": bool(permissions.get("crm_writes_enabled")),
        },
        "enabled_modules": enabled,
        "modules": modules,
    }


def connector_gaps(profile: dict) -> list[str]:
    gaps = []
    for module_id in ("mail-sweep", "calendar-sweep"):
        module = (profile.get("modules") or {}).get(module_id) or {}
        for provider in module.get("providers") or []:
            if provider.get("adapter") == "outlook-com" and platform.system() != "Windows":
                gaps.append(f"{module_id}: Outlook COM is Windows-only; configure a connector")
                continue
            if not provider.get("configured"):
                gaps.append(f"{module_id}: {provider.get('provider')} connector is not marked configured")
    optional = profile.get("modules") or {}
    for module_id, connector in (("slack-sweep", "slack"), ("granola-meetings", "granola"), ("source-of-truth", "atlassian")):
        module = optional.get(module_id) or {}
        if module.get("enabled") and not module.get("connector_configured", False):
            gaps.append(f"{module_id}: {connector} connector is not marked configured")
    if ((profile.get("artifacts") or {}).get("exports") or {}).get("xlsx"):
        if importlib.util.find_spec("openpyxl") is None:
            gaps.append("XLSX export: optional dependency openpyxl is not installed")
    if ((profile.get("modules") or {}).get("crm-google-sheet") or {}).get("enabled"):
        if importlib.util.find_spec("openpyxl") is None:
            gaps.append("CRM workbook: optional dependency openpyxl is not installed")
    return gaps


def validate_setup(profile: dict, strict_paths: bool = False) -> dict:
    errors, warnings = validate_profile(profile, strict_paths=strict_paths)
    gaps = connector_gaps(profile)
    status = "blocked" if errors else "usable_with_gaps" if warnings or gaps else "ready"
    return {
        "status": status,
        "blockers": errors,
        "gaps": [*warnings, *gaps],
        "notes": ["External writes remain proposal-gated."] if not errors else [],
        "profile_id": (profile.get("profile") or {}).get("id"),
        "enabled_modules": profile.get("enabled_modules") or [],
    }


def create_workspace(profile: dict) -> list[str]:
    created = []
    for path_text in resolved_artifact_paths(profile["artifacts"]).values():
        path = Path(path_text)
        existed = path.exists()
        path.mkdir(parents=True, exist_ok=True)
        if not existed:
            created.append(str(path))
    modules = profile.get("modules") or {}
    crm = modules.get("crm-google-sheet") or {}
    if crm.get("enabled"):
        workbook = Path(crm["workbook_path"])
        if not workbook.exists() and importlib.util.find_spec("openpyxl") is not None:
            from generate_crm_workbook import create_workbook

            create_workbook(workbook, Path(crm["csv_seed_dir"]))
            created.extend([str(workbook), crm["csv_seed_dir"]])
        Path(crm["proposal_output_dir"]).mkdir(parents=True, exist_ok=True)
    source = modules.get("source-of-truth") or {}
    if source.get("enabled") and source.get("mode") == "local_files":
        mapping = Path(source["mapping_path"])
        if not mapping.exists():
            mapping.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(mapping, "Type,Name,Canonical URL,Status,Last Reviewed,Notes\n")
            created.append(str(mapping))
    return created


def rebase_dry_run_paths(profile: dict, workspace: Path) -> None:
    profile["artifacts"]["workspace_root"] = str(workspace)
    profile["artifacts"]["path_overrides"] = {}
    modules = profile.get("modules") or {}
    crm = modules.get("crm-google-sheet") or {}
    if crm.get("enabled"):
        crm["workbook_path"] = str(workspace / "CRM" / "close-day-crm.xlsx")
        crm["csv_seed_dir"] = str(workspace / "CRM" / "csv_seed")
        crm["proposal_output_dir"] = str(workspace / "CRM" / "proposals")
    source = modules.get("source-of-truth") or {}
    if source.get("enabled") and source.get("mode") == "local_files":
        source["mapping_path"] = str(workspace / "Source of Truth" / "source-of-truth-map.csv")


def write_report(directory: Path, validation: dict, created: list[str], profile_path_value: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(directory / "access-check.json", {
        **validation,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "profile_path": str(profile_path_value),
        "created": created,
    })
    lines = [
        "# close-day onboarding report", "",
        f"Status: {validation['status']}",
        f"Profile: {validation.get('profile_id')}", "",
        "## Created", "", *([f"- {item}" for item in created] or ["- None"]), "",
        "## Gaps", "", *([f"- {item}" for item in validation["gaps"]] or ["- None"]), "",
        "## Blockers", "", *([f"- {item}" for item in validation["blockers"]] or ["- None"]), "",
    ]
    atomic_write_text(directory / "setup-report.md", "\n".join(lines))


def question_catalog() -> dict:
    manifests = load_manifests()
    return {
        "schema_version": SCHEMA_VERSION,
        "answer_file": "config/onboarding.answers.example.json",
        "core_questions": [
            "What named close profile should be created?",
            "Which personal and organization scopes belong in this profile?",
            "Which aliases, domains, source bindings, and exclusions classify each scope?",
            "What workspace root should contain Plans, Agendas, Tasks, Logs, and State?",
            "Which Google and Microsoft mail/calendar providers are connected?",
            "Which optional meeting, chat, CRM, Jira, and source-of-truth modules are needed?",
            "Which local and external writes are allowed after approval?",
            "Should Daily Takeaways, recurring recaps, DOCX, and XLSX exports be enabled?",
        ],
        "modules": {key: value.get("onboarding", {}) for key, value in manifests.items()},
    }


def llm_prompt() -> str:
    return (
        "Onboard close-day using outcome-oriented questions. Do not request raw source content. "
        "Return JSON matching this schema and pause before creating files.\n\n"
        f"```json\n{json.dumps(default_answers(), indent=2)}\n```\n"
    )


def run_command(args: argparse.Namespace) -> int:
    answers = load_json(Path(args.answers).expanduser()) if args.answers else collect_interactive_answers()
    profile = build_profile(answers)
    preflight = validate_setup(profile)
    if preflight["status"] == "blocked":
        print(json.dumps(preflight, indent=2))
        return 1
    if args.dry_run:
        root = DEFAULT_REPORT_DIR / "dry-run-config"
        workspace = DEFAULT_REPORT_DIR / "dry-run-workspace"
        rebase_dry_run_paths(profile, workspace)
        destination = profile_path(profile["profile"]["id"], root)
        atomic_write_json(destination, profile)
        created = create_workspace(profile)
        validation = validate_setup(profile)
        write_report(DEFAULT_REPORT_DIR, validation, created, destination)
    else:
        if not args.approved:
            summary = {
                "profile": profile["profile"],
                "scopes": profile["scopes"],
                "workspace_paths": resolved_artifact_paths(profile["artifacts"]),
                "permissions": profile["permissions"],
                "enabled_modules": profile["enabled_modules"],
            }
            print(json.dumps(summary, indent=2))
            if args.answers or not yes_no("Create this profile and its local folders?", False):
                print("approval required; rerun with --approved after reviewing the dry run", file=sys.stderr)
                return 2
        root = Path(args.config_root).expanduser() if args.config_root else default_config_root()
        existing_profile = profile_path(profile["profile"]["id"], root)
        if existing_profile.exists() and not args.replace:
            print(
                f"profile already exists: {existing_profile}; use --replace after reviewing a dry run",
                file=sys.stderr,
            )
            return 2
        created = create_workspace(profile)
        destination = register_profile(profile, root, make_default=args.make_default)
        validation = validate_setup(profile)
        write_report(Path(args.report_dir).expanduser() if args.report_dir else root / "reports", validation, created, destination)
    print(json.dumps({**validation, "profile_path": str(destination), "created": created}, indent=2))
    return 1 if validation["status"] == "blocked" else 0


def migrate_command(args: argparse.Namespace) -> int:
    legacy_path = Path(args.from_path).expanduser()
    legacy = load_json(legacy_path)
    profile = migrate_v1_profile(legacy, args.profile_id, args.workspace_root)
    errors, warnings = validate_profile(profile)
    preview = {"profile": profile, "errors": errors, "warnings": warnings, "legacy_retained": str(legacy_path)}
    if args.dry_run:
        print(json.dumps(preview, indent=2))
        return 1 if errors else 0
    if not args.approved:
        print("migration approval required; review --dry-run then rerun with --approved", file=sys.stderr)
        return 2
    if errors:
        print(json.dumps(preview, indent=2))
        return 1
    root = Path(args.config_root).expanduser() if args.config_root else default_config_root()
    existing_profile = profile_path(profile["profile"]["id"], root)
    if existing_profile.exists() and not args.replace:
        print(
            f"profile already exists: {existing_profile}; choose another id or use --replace",
            file=sys.stderr,
        )
        return 2
    destination = register_profile(profile, root, make_default=args.make_default)
    created = create_workspace(profile) if args.create_folders else []
    validation = validate_setup(profile)
    write_report(root / "reports", validation, created, destination)
    print(json.dumps({**validation, "profile_path": str(destination), "legacy_retained": str(legacy_path)}, indent=2))
    return 0


def validate_command(args: argparse.Namespace) -> int:
    if args.config:
        profile = load_json(Path(args.config).expanduser())
    else:
        profile, _ = resolve_profile(args.profile, Path(args.config_root).expanduser() if args.config_root else None)
    validation = validate_setup(profile, strict_paths=args.strict_paths)
    print(json.dumps(validation, indent=2))
    return 1 if validation["status"] == "blocked" else 0


def questions_command(args: argparse.Namespace) -> int:
    payload: Any = question_catalog() if args.json else llm_prompt()
    rendered = json.dumps(payload, indent=2) if args.json else payload
    if args.out:
        destination = Path(args.out).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(destination, rendered if rendered.endswith("\n") else rendered + "\n")
        print(f"wrote: {destination}")
    else:
        print(rendered)
    return 0


def profiles_command(args: argparse.Namespace) -> int:
    root = Path(args.config_root).expanduser() if args.config_root else default_config_root()
    registry = load_registry(root)
    if args.profile_action == "list":
        print(json.dumps(registry, indent=2))
        return 0
    selected = args.profile_id
    if not any(record.get("id") == selected for record in registry.get("profiles") or []):
        raise FileNotFoundError(f"profile not registered: {selected}")
    registry["default_profile_id"] = selected
    atomic_write_json(registry_path(root), registry)
    print(f"default profile: {selected}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Install and configure schema-v2 close-day profiles.")
    sub = parser.add_subparsers(dest="command", required=True)

    questions = sub.add_parser("questions", help="Emit onboarding questions and answer schema.")
    questions.add_argument("--out")
    questions.add_argument("--json", action="store_true")
    questions.set_defaults(func=questions_command)

    run = sub.add_parser("run", help="Create a named profile from answers.")
    run.add_argument("--answers")
    run.add_argument("--config-root")
    run.add_argument("--report-dir")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--approved", action="store_true", help="Confirm the reviewed profile and folder writes.")
    run.add_argument("--make-default", action="store_true")
    run.add_argument("--replace", action="store_true", help="Replace an existing profile after dry-run review.")
    run.set_defaults(func=run_command)

    migrate = sub.add_parser("migrate", help="Preview or migrate a schema-v1 local config.")
    migrate.add_argument("--from", dest="from_path", required=True)
    migrate.add_argument("--profile-id")
    migrate.add_argument("--workspace-root")
    migrate.add_argument("--config-root")
    migrate.add_argument("--dry-run", action="store_true")
    migrate.add_argument("--approved", action="store_true", help="Confirm the reviewed migration.")
    migrate.add_argument("--make-default", action="store_true")
    migrate.add_argument("--create-folders", action="store_true")
    migrate.add_argument("--replace", action="store_true", help="Replace an existing migrated profile after review.")
    migrate.set_defaults(func=migrate_command)

    validate = sub.add_parser("validate", help="Validate a profile and readiness.")
    validate.add_argument("--config")
    validate.add_argument("--profile")
    validate.add_argument("--config-root")
    validate.add_argument("--strict-paths", action="store_true")
    validate.set_defaults(func=validate_command)

    profiles = sub.add_parser("profiles", help="List profiles or set the default.")
    profiles.add_argument("profile_action", choices=("list", "set-default"))
    profiles.add_argument("profile_id", nargs="?")
    profiles.add_argument("--config-root")
    profiles.set_defaults(func=profiles_command)

    args = parser.parse_args()
    if args.command == "profiles" and args.profile_action == "set-default" and not args.profile_id:
        parser.error("profiles set-default requires profile_id")
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("canceled", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
