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


def bounded_int(prompt: str, default: int, minimum: int, maximum: int) -> int:
    while True:
        value = ask(prompt, str(default))
        try:
            parsed = int(value)
        except ValueError:
            print(f"Enter a whole number from {minimum} to {maximum}.")
            continue
        if minimum <= parsed <= maximum:
            return parsed
        print(f"Enter a whole number from {minimum} to {maximum}.")


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

    optional = answers["systems"].setdefault("optional_modules", {})
    if yes_no("Enable a scoped Jira sweep?", False):
        jira_scope = ask(f"Jira scope id ({', '.join(scope_ids)})", scope_ids[-1])
        optional["jira-sweep"] = {
            "enabled": True,
            "connector": "atlassian",
            "connector_configured": yes_no("Is the Jira connector authenticated?", False),
            "queries": [{
                "name": ask("Jira query name", "Assigned open work"),
                "jql": ask(
                    "JQL",
                    "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC",
                ),
                "scope_id": jira_scope,
                "limit": 50,
            }],
        }
        if yes_no("Use Jira as an approved action destination for team or multi-step work?", False):
            optional["jira-sweep"]["writes"] = {
                "enabled": True,
                "scope_ids": [jira_scope],
                "projects": {
                    jira_scope: {
                        "project_key": ask("Jira project key"),
                        "issue_type": ask("Default Jira issue type", "Task"),
                        "assignee_account_id": ask("Default Jira assignee account id (optional)") or None,
                    }
                },
                "allowed_operations": ["create", "update", "comment", "transition"],
                "duplicate_check": True,
            }
            answers["permissions"]["jira_writes_enabled"] = True

    if yes_no("Connect an existing Google Sheet as the GTD action system?", False):
        sheet_ref = ask("Google Sheet URL or spreadsheet id")
        selected_scopes = [
            value.strip()
            for value in ask("GTD scope ids (comma-separated)", ",".join(scope_ids)).split(",")
            if value.strip()
        ]
        area_values = {
            scope_id: ask(f"GTD Area value for {scope_id}", scope_id)
            for scope_id in selected_scopes
        }
        allow_gtd_writes = yes_no(
            "Allow exact GTD row writes after the consolidated close approval?", False
        )
        optional["gtd-google-sheet"] = {
            "enabled": True,
            "connector": "google-drive",
            "connector_configured": yes_no("Is the Google Drive connector authenticated?", False),
            **(
                {"spreadsheet_url": sheet_ref}
                if sheet_ref.startswith("http")
                else {"spreadsheet_id": sheet_ref}
            ),
            "scope_ids": selected_scopes,
            "area_values": area_values,
            "tab_map": {
                "next_actions": ask("Next Actions tab", "Next Actions"),
                "waiting_fors": ask("Waiting Fors tab", "Waiting Fors"),
                "inbox": ask("Inbox tab", "Inbox"),
                "archive": ask("Archive tab", "Action Archive"),
            },
            "project_tabs": {
                scope_id: ask(f"Projects tab for {scope_id} (optional)") or None
                for scope_id in selected_scopes
            },
            "archive_before_clear": True,
            "allow_writes": allow_gtd_writes,
        }
        answers["permissions"]["gtd_writes_enabled"] = allow_gtd_writes
    if yes_no("Enable a scoped local-folder sweep?", False):
        roots = []
        while True:
            root_path = ask("Approved local folder root")
            root_scope = ask(f"Folder scope id ({', '.join(scope_ids)})", scope_ids[-1])
            roots.append({
                "path": root_path,
                "scope_id": root_scope,
                "recursive": True,
                "lookback_days": 7,
                "include_extensions": [],
            })
            if not yes_no("Add another local folder root?", False):
                break
        optional["local-files"] = {
            "enabled": True,
            "roots": roots,
            "max_files": 200,
            "max_scanned_files": 5000,
            "max_scanned_directories": 1000,
            "max_scan_seconds": 15,
        }

    if yes_no("Include a CRM review in each close?", False):
        crm_scope = ask(f"CRM scope id ({', '.join(scope_ids)})", scope_ids[-1])
        delegated = yes_no("Use an existing specialized CRM handler skill?", True)
        allow_live_writes = yes_no(
            "Allow exact CRM cell writes after the consolidated close approval?", False
        )
        if delegated:
            handler_skill = ask("CRM handler skill name", "update-crm")
            handler_path = ask("CRM handler SKILL.md path (optional)")
            optional["crm-google-sheet"] = {
                "enabled": True,
                "mode": "delegated_handler",
                "scope_ids": [crm_scope],
                "handler_skill": handler_skill,
                **({"handler_path": handler_path} if handler_path else {}),
                "review_mode": "incremental_daily",
                "first_run_lookback_days": bounded_int(
                    "First CRM review lookback in days", 14, 1, 365
                ),
                "overlap_hours": bounded_int(
                    "CRM review overlap in hours", 24, 0, 168
                ),
                "allow_new_rows": yes_no(
                    "Propose new rows for clearly identified contacts?", True
                ),
                "minimum_confidence": ask(
                    "Minimum proposed inference confidence (medium/high)", "medium"
                ).lower(),
                "allow_live_sheet_writes": allow_live_writes,
                "roll_weekly_jira": False,
            }
        else:
            optional["crm-google-sheet"] = {
                "enabled": True,
                "mode": "portable_workbook",
                "allow_live_sheet_writes": allow_live_writes,
            }
        answers["permissions"]["crm_writes_enabled"] = allow_live_writes

    action_destinations = {}
    jira_config = optional.get("jira-sweep") or {}
    if (jira_config.get("writes") or {}).get("enabled"):
        action_destinations["jira"] = "jira-sweep"
    gtd_config = optional.get("gtd-google-sheet") or {}
    if gtd_config.get("enabled") and gtd_config.get("allow_writes"):
        action_destinations["gtd"] = "gtd-google-sheet"
    crm_config = optional.get("crm-google-sheet") or {}
    if crm_config.get("enabled") and crm_config.get("allow_live_sheet_writes"):
        action_destinations["crm"] = "crm-google-sheet"
    if action_destinations and yes_no(
        "Route every action to one primary system and use linked records for overlaps?", True
    ):
        choices = ", ".join([*action_destinations, "drop"])
        team_destination = ask(
            f"Primary destination for team, delegated, multi-step work ({choices})",
            "jira" if "jira" in action_destinations else "gtd",
        ).lower()
        personal_destination = ask(
            f"Primary destination for personal and small next actions ({choices})",
            "gtd" if "gtd" in action_destinations else team_destination,
        ).lower()
        waiting_destination = ask(
            f"Primary destination for waiting-fors ({choices})", personal_destination
        ).lower()
        crm_record_destination = ask(
            f"Primary destination for non-executable CRM record updates ({choices})",
            "crm" if "crm" in action_destinations else "drop",
        ).lower()
        optional["action-routing"] = {
            "enabled": True,
            "overlap_policy": "primary_with_links",
            "unready_policy": "pause_and_ask",
            "destinations": action_destinations,
            "rules": {
                "team_project_work": team_destination,
                "delegated_work": team_destination,
                "next_action": personal_destination,
                "personal_next_action": personal_destination,
                "follow_up": personal_destination,
                "waiting_for": waiting_destination,
                "crm_record_update": crm_record_destination,
            },
        }

    excluded = [value.strip() for value in ask("Globally excluded topics (comma-separated)").split(",") if value.strip()]
    answers["routing"]["global_exclusions"] = [
        {"name": value, "match_terms": [value], "reason": "User-requested during onboarding"}
        for value in excluded
    ]
    answers["permissions"]["local_artifact_writes_enabled"] = yes_no(
        "Allow local artifact creation after approval?", True
    )
    answers["artifacts"]["exports"]["daily_plan_docx"] = yes_no(
        "Export the Daily Plan as DOCX?", False
    )
    answers["artifacts"]["exports"]["agenda_docx"] = yes_no(
        "Export standalone meeting agendas as DOCX?", False
    )
    answers["artifacts"]["exports"]["xlsx"] = yes_no("Export XLSX task workbooks?", False)
    takeaway = answers["features"].setdefault("daily_takeaways", {})
    takeaway["enabled"] = yes_no("Include yesterday/today reflections in the Daily Plan?", True)
    if takeaway["enabled"]:
        takeaway["required_items"] = bounded_int(
            "How many items are required in each reflection list?", 3, 0, 3
        )
        takeaway["max_items"] = max(
            int(takeaway.get("max_items") or 3), takeaway["required_items"]
        )
        takeaway["incomplete_policy"] = (
            "ask_until_complete"
            if yes_no("Pause and ask until both reflection lists are complete?", True)
            else "allow_partial"
        )

    optional = answers["systems"].setdefault("optional_modules", {})
    if yes_no("Email the Daily Plan after the approved close is finalized?", False):
        sender = ask("Authenticated Gmail sender", owner.get("primary_email") or "")
        recipients = [
            value.strip()
            for value in ask("Delivery recipients (comma-separated)", owner.get("primary_email") or "").split(",")
            if value.strip()
        ]
        mode = (
            "send_after_approved_close"
            if yes_no("Send immediately after finalization (instead of creating a draft)?", True)
            else "draft_after_approved_close"
        )
        attach_plan = yes_no("Attach the Daily Plan DOCX?", True)
        if attach_plan:
            answers["artifacts"]["exports"]["daily_plan_docx"] = True
        optional["email-delivery"] = {
            "enabled": True,
            "provider": "gmail",
            "connector": "gmail",
            "connector_configured": yes_no(
                "Is the Gmail connector authenticated as this sender?", False
            ),
            "from": sender,
            "recipients": recipients,
            "mode": mode,
            "subject_template": ask(
                "Email subject template", "Daily Success Plan for {target_date}"
            ),
            "body_style": ask("Email body style (summary/full_plan)", "summary"),
            "attachments": ["daily_plan_docx"] if attach_plan else [],
        }
        answers["permissions"]["email_delivery_enabled"] = True
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
    export_answers = artifacts.get("exports") or {}

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
    for module_id in (
        "granola-meetings",
        "slack-sweep",
        "jira-sweep",
        "gtd-google-sheet",
        "action-routing",
        "local-files",
        "teams-local-cache",
        "source-of-truth",
        "crm-google-sheet",
        "email-delivery",
    ):
        value = dict(optional.get(module_id) or {})
        if value.get("enabled"):
            workspace = Path(artifacts.get("workspace_root") or Path.home() / "Documents" / "close-day").expanduser()
            if module_id == "jira-sweep":
                value.setdefault("connector", "atlassian")
                value.setdefault("connector_configured", False)
                value.setdefault("queries", [])
                if (value.get("writes") or {}).get("enabled"):
                    value["writes"].setdefault(
                        "allowed_operations", ["create", "update", "comment", "transition"]
                    )
                    value["writes"].setdefault("duplicate_check", True)
            if module_id == "gtd-google-sheet":
                value.setdefault("connector", "google-drive")
                value.setdefault("connector_configured", False)
                value.setdefault("tab_map", {
                    "next_actions": "Next Actions",
                    "waiting_fors": "Waiting Fors",
                    "inbox": "Inbox",
                    "archive": "Action Archive",
                })
                value.setdefault("area_values", {})
                value.setdefault("archive_before_clear", True)
                value.setdefault("allow_writes", False)
            if module_id == "action-routing":
                value.setdefault("overlap_policy", "primary_with_links")
                value.setdefault("unready_policy", "pause_and_ask")
                value.setdefault("destinations", {})
                value.setdefault("rules", {})
            if module_id == "local-files":
                value.setdefault("roots", [])
                value.setdefault("max_files", 200)
                value.setdefault("max_scanned_files", 5000)
                value.setdefault("max_scanned_directories", 1000)
                value.setdefault("max_scan_seconds", 15)
            if module_id == "crm-google-sheet":
                value.setdefault("mode", "portable_workbook")
                value.setdefault("allow_live_sheet_writes", False)
                if value["mode"] == "portable_workbook":
                    value.setdefault("workbook_path", str(workspace / "CRM" / "close-day-crm.xlsx"))
                    value.setdefault("proposal_output_dir", str(workspace / "CRM" / "proposals"))
                    value.setdefault("csv_seed_dir", str(workspace / "CRM" / "csv_seed"))
                else:
                    value.setdefault("review_mode", "incremental_daily")
                    value.setdefault("first_run_lookback_days", 14)
                    value.setdefault("overlap_hours", 24)
                    value.setdefault("allow_new_rows", False)
                    value.setdefault("minimum_confidence", "high")
                    value.setdefault("roll_weekly_jira", False)
            if module_id == "source-of-truth":
                value.setdefault("mode", "local_files")
                value.setdefault("allow_confluence_writes", False)
                value.setdefault("mapping_path", str(workspace / "Source of Truth" / "source-of-truth-map.csv"))
            if module_id == "email-delivery":
                value.setdefault("provider", "gmail")
                value.setdefault("connector", "gmail")
                value.setdefault("connector_configured", False)
                value.setdefault("mode", "send_after_approved_close")
                value.setdefault("subject_template", "Daily Success Plan for {target_date}")
                value.setdefault("body_style", "summary")
                value.setdefault("attachments", ["daily_plan_docx"])
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
                "docx": bool(export_answers.get("docx")),
                "xlsx": bool(export_answers.get("xlsx")),
                **{
                    key: bool(export_answers[key])
                    for key in ("daily_plan_docx", "agenda_docx")
                    if key in export_answers
                },
            },
        },
        "features": {
            "daily_takeaways": {
                "enabled": bool(takeaway.get("enabled", personal_or_mixed)),
                "max_items": int(takeaway.get("max_items") or 3),
                "required_items": int(takeaway.get("required_items") or 0),
                "incomplete_policy": takeaway.get("incomplete_policy") or "allow_partial",
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
            "jira_writes_enabled": bool(permissions.get("jira_writes_enabled")),
            "gtd_writes_enabled": bool(permissions.get("gtd_writes_enabled")),
            "crm_writes_enabled": bool(permissions.get("crm_writes_enabled")),
            "email_delivery_enabled": bool(permissions.get("email_delivery_enabled")),
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
                account = provider.get("account")
                identity = f" for {account}" if account else ""
                gaps.append(
                    f"{module_id}: {provider.get('provider')} connector{identity} is not marked configured"
                )
    optional = profile.get("modules") or {}
    for module_id, connector in (
        ("slack-sweep", "slack"),
        ("jira-sweep", "atlassian/Jira"),
        ("gtd-google-sheet", "Google Drive/Sheets"),
        ("granola-meetings", "granola"),
        ("source-of-truth", "atlassian"),
        ("email-delivery", "Gmail"),
    ):
        module = optional.get(module_id) or {}
        if module.get("enabled") and not module.get("connector_configured", False):
            gaps.append(f"{module_id}: {connector} connector is not marked configured")
    local_files = optional.get("local-files") or {}
    if local_files.get("enabled"):
        for root in local_files.get("roots") or []:
            path = Path(root.get("path") or "").expanduser()
            if not path.is_dir():
                gaps.append(f"local-files: root does not exist or is not a directory: {path}")
    if ((profile.get("artifacts") or {}).get("exports") or {}).get("xlsx"):
        if importlib.util.find_spec("openpyxl") is None:
            gaps.append("XLSX export: optional dependency openpyxl is not installed")
    if ((profile.get("modules") or {}).get("crm-google-sheet") or {}).get("enabled"):
        crm = (profile.get("modules") or {}).get("crm-google-sheet") or {}
        if crm.get("mode", "portable_workbook") == "portable_workbook":
            if importlib.util.find_spec("openpyxl") is None:
                gaps.append("CRM workbook: optional dependency openpyxl is not installed")
        else:
            configured_path = crm.get("handler_path")
            candidate = (
                Path(configured_path).expanduser()
                if configured_path
                else Path.home() / ".codex" / "skills" / str(crm.get("handler_skill") or "") / "SKILL.md"
            )
            if not candidate.is_file():
                gaps.append(
                    f"CRM handler skill is not available at the configured path: {candidate}"
                )
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
    if crm.get("enabled") and crm.get("mode", "portable_workbook") == "portable_workbook":
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
    if crm.get("enabled") and crm.get("mode", "portable_workbook") == "portable_workbook":
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
            "Which durable systems may own actions: Jira, a GTD Google Sheet, CRM records, or a configured subset?",
            "For overlapping work, should one primary action own execution while CRM or other systems hold linked secondary records?",
            "If a GTD Google Sheet is used, what are its URL or id, scope-to-Area values, project tabs, Next Actions tab, Waiting Fors tab, Inbox tab, and Archive tab?",
            "Should completed GTD rows always be archived before they are cleared from active tabs?",
            "May Jira create, update, comment, and transition approved work, and which project, issue type, assignee, and scope apply?",
            "Should CRM use a portable workbook or delegate an incremental review to a configured handler skill, for which scopes and confidence threshold?",
            "Which exact local folders may be read, and which scope owns each folder?",
            "Which local and external writes are allowed after approval?",
            "Should Daily Takeaways require an exact count, and should an incomplete close pause for answers?",
            "Should Daily Plan DOCX, agenda DOCX, and XLSX exports be enabled separately?",
            "Should a finalized plan be sent or drafted by email after the one consolidated close approval, from which Gmail account, to which recipients, with what subject, body style, and attachment?",
            "Does Gmail offer a narrow send-email approval override, or should its platform confirmation remain enabled?",
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
