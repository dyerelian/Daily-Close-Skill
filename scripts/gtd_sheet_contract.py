#!/usr/bin/env python3
"""Schema and write-plan contract for a live Google Sheets GTD system."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from close_day_config import atomic_write_text, load_json, resolve_profile, validate_profile


DEFAULT_HEADERS = {
    "next_actions": [
        "Area", "Related Project", "Next Action", "Context", "Category", "Defer / Review On",
        "Due", "Priority", "Status", "Close Action ID", "Source Provider", "Source ID",
        "Source Link", "External Key", "Created At", "Last Synced At",
    ],
    "waiting_fors": [
        "Waiting For", "Owner", "Status", "Related Project", "Since", "Follow-up Date", "Area",
        "Close Action ID", "Source Provider", "Source ID", "Source Link", "External Key",
        "Created At", "Last Synced At",
    ],
    "inbox": [
        "Captured Item", "Area", "Captured At", "Review By", "Proposed Destination", "Status", "Notes",
        "Close Action ID", "Source Provider", "Source ID", "Source Link", "External Key",
        "Created At", "Last Synced At",
    ],
    "archive": [
        "Area", "Related Project", "Item", "Kind", "Owner", "Due / Follow-up", "Final Status",
        "Completed At", "Primary Destination", "External Key", "Source Link", "Close Action ID", "Origin Tab",
    ],
}
REQUIRED_TAB_KEYS = tuple(DEFAULT_HEADERS)


def _text(value: object) -> str:
    return str(value or "").strip()


def _module(profile: dict) -> dict:
    return (profile.get("modules") or {}).get("gtd-google-sheet") or {}


def _context_values(profile: dict) -> list[str]:
    return list(
        _module(profile).get("context_values")
        or ["@Computer", "@Calls", "@Errands", "@Anywhere"]
    )


def audit_gtd_schema(headers_by_tab: dict[str, list[str]], module: dict) -> dict:
    """Compare configured tabs with their required durable action headers."""
    errors = []
    tabs = module.get("tab_map") or {}
    configured_headers = module.get("headers") or {}
    for key in REQUIRED_TAB_KEYS:
        tab = tabs.get(key)
        if not _text(tab):
            errors.append(f"tab_map.{key} is required")
            continue
        actual = headers_by_tab.get(tab)
        if actual is None:
            errors.append(f"configured tab is missing: {tab}")
            continue
        required = configured_headers.get(key) or DEFAULT_HEADERS[key]
        if actual[: len(required)] != required:
            errors.append(f"{tab} headers do not match the configured {key} contract")
    if module.get("archive_before_clear") is not True:
        errors.append("archive_before_clear must be true")
    return {"valid": not errors, "errors": errors}


def build_gtd_operations(action_proposal: dict, profile: dict) -> list[dict]:
    """Translate primary GTD actions into canonical row operations."""
    module = _module(profile)
    tabs = module.get("tab_map") or {}
    area_values = module.get("area_values") or {}
    operations = []
    for item in action_proposal.get("items") or []:
        if item.get("primary_destination") != "gtd":
            continue
        kind = _text(item.get("action_kind")).casefold()
        waiting = kind == "waiting_for"
        tab_key = "waiting_fors" if waiting else "next_actions"
        source = item.get("source") or {}
        common = {
            "Close Action ID": item.get("close_action_id"),
            "Source Provider": source.get("provider") or item.get("source_provider"),
            "Source ID": source.get("id") or item.get("source_id"),
            "Source Link": source.get("link") or item.get("source_link"),
            "External Key": item.get("external_key"),
            "Created At": item.get("created_at"),
            "Last Synced At": item.get("last_synced_at"),
        }
        if waiting:
            row = {
                "Waiting For": item.get("title"),
                "Owner": item.get("owner"),
                "Status": item.get("status") or "Waiting",
                "Related Project": item.get("related_project"),
                "Since": item.get("since"),
                "Follow-up Date": item.get("follow_up_date") or item.get("due"),
                "Area": area_values.get(item.get("scope_id")),
                **common,
            }
        else:
            source_due = item.get("due")
            hard_due = item.get("hard_due") or (
                source_due if item.get("due_is_hard") is True else None
            )
            review_on = item.get("defer_until") or item.get("review_on")
            if not review_on and source_due and item.get("due_is_hard") is not True:
                review_on = source_due
            row = {
                "Area": area_values.get(item.get("scope_id")),
                "Related Project": item.get("related_project"),
                "Next Action": item.get("title"),
                "Context": item.get("context") or "@Anywhere",
                "Category": item.get("category") or "Task",
                "Defer / Review On": review_on,
                "Due": hard_due,
                "Priority": item.get("priority"),
                "Status": item.get("status") or "Active",
                **common,
            }
        operations.append(
            {
                "operation": "upsert",
                "tab_key": tab_key,
                "tab": tabs.get(tab_key),
                "scope_id": item.get("scope_id"),
                "close_action_id": item.get("close_action_id"),
                "row": row,
            }
        )
    return operations


def validate_gtd_operations(
    operations: Iterable[dict], profile: dict, approved_ids: Iterable[str] | None = None
) -> list[str]:
    module = _module(profile)
    permissions = profile.get("permissions") or {}
    scopes = {scope.get("id") for scope in profile.get("scopes") or []}
    area_values = module.get("area_values") or {}
    tabs = module.get("tab_map") or {}
    contexts = set(_context_values(profile))
    errors = []
    approved = set(approved_ids) if approved_ids is not None else None
    if not module.get("enabled"):
        errors.append("modules.gtd-google-sheet is not enabled")
    if not module.get("allow_writes", False):
        errors.append("modules.gtd-google-sheet.allow_writes is false")
    if not permissions.get("gtd_writes_enabled", False):
        errors.append("permissions.gtd_writes_enabled is false")
    seen = set()
    for index, operation in enumerate(operations):
        label = f"operations[{index}]"
        action_id = _text(operation.get("close_action_id"))
        if not action_id:
            errors.append(f"{label}.close_action_id is required")
        elif action_id in seen:
            errors.append(f"duplicate close_action_id in GTD operations: {action_id}")
        else:
            seen.add(action_id)
        if approved is not None and action_id not in approved:
            errors.append(f"{label}: exact action approval is missing")
        if operation.get("scope_id") not in scopes:
            errors.append(f"{label}.scope_id must reference a configured scope")
        elif not _text(area_values.get(operation.get("scope_id"))):
            errors.append(f"{label}.scope_id has no GTD Area mapping")
        op_type = operation.get("operation")
        if op_type == "upsert":
            if operation.get("tab") not in {tabs.get("next_actions"), tabs.get("waiting_fors"), tabs.get("inbox")}:
                errors.append(f"{label}.tab is not an allowed active GTD tab")
            if not isinstance(operation.get("row"), dict):
                errors.append(f"{label}.row must be an object")
            elif operation.get("tab") == tabs.get("next_actions"):
                context = _text(operation["row"].get("Context"))
                if context not in contexts:
                    errors.append(f"{label}.row.Context is not configured: {context}")
        elif op_type == "archive_and_clear":
            if module.get("archive_before_clear") is not True:
                errors.append(f"{label}: archive_before_clear is required")
            if not isinstance(operation.get("archive_record"), dict):
                errors.append(f"{label}.archive_record is required")
            if operation.get("origin_tab") not in {tabs.get("next_actions"), tabs.get("waiting_fors"), tabs.get("inbox")}:
                errors.append(f"{label}.origin_tab is not an active GTD tab")
        else:
            errors.append(f"{label}.operation must be upsert or archive_and_clear")
    return errors


def build_write_plan(
    operations: Iterable[dict], profile: dict, existing_index: dict[str, dict] | None = None
) -> list[dict]:
    """Order connector writes so archive always precedes destructive clearing."""
    tabs = _module(profile).get("tab_map") or {}
    existing = existing_index or {}
    plan = []
    for operation in operations:
        action_id = operation["close_action_id"]
        if operation["operation"] == "archive_and_clear":
            plan.append(
                {
                    "action": "append",
                    "tab": tabs.get("archive"),
                    "close_action_id": action_id,
                    "row": operation["archive_record"],
                }
            )
            plan.append(
                {
                    "action": "clear",
                    "tab": operation["origin_tab"],
                    "row_number": operation.get("row_number"),
                    "close_action_id": action_id,
                    "depends_on": f"archive:{action_id}",
                }
            )
            continue
        match = existing.get(action_id)
        plan.append(
            {
                "action": "update" if match else "append",
                "tab": match.get("tab") if match else operation["tab"],
                "row_number": match.get("row_number") if match else None,
                "close_action_id": action_id,
                "dedupe_by": "Close Action ID",
                "row": operation["row"],
            }
        )
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit or build Google Sheets GTD write plans.")
    parser.add_argument("command", choices=("audit", "build", "validate"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--profile-file")
    parser.add_argument("--config-root")
    parser.add_argument("--approved-id", action="append", default=[])
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.profile_file:
        profile = load_json(Path(args.profile_file).expanduser())
    else:
        profile, _ = resolve_profile(args.profile, Path(args.config_root).expanduser() if args.config_root else None)
    errors, _ = validate_profile(profile)
    if errors:
        raise ValueError("invalid profile: " + "; ".join(errors))
    payload = load_json(Path(args.input).expanduser())
    if args.command == "audit":
        result = audit_gtd_schema(payload, _module(profile))
        exit_code = 1 if result["errors"] else 0
    elif args.command == "build":
        operations = build_gtd_operations(payload, profile)
        operation_errors = validate_gtd_operations(operations, profile, args.approved_id)
        result = {
            "valid": not operation_errors,
            "errors": operation_errors,
            "operations": operations,
            "write_plan": build_write_plan(operations, profile) if not operation_errors else [],
        }
        exit_code = 1 if operation_errors else 0
    else:
        operations = payload.get("operations") if isinstance(payload, dict) else payload
        operation_errors = validate_gtd_operations(operations or [], profile, args.approved_id)
        result = {"valid": not operation_errors, "errors": operation_errors}
        exit_code = 1 if operation_errors else 0
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        atomic_write_text(Path(args.output).expanduser(), rendered)
    else:
        sys.stdout.write(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
