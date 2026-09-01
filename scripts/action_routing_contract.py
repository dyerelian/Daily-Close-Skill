#!/usr/bin/env python3
"""Deterministic primary-destination routing for close-day action items."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Iterable

from close_day_config import atomic_write_text, load_json, resolve_profile, validate_profile


DESTINATIONS = {"gtd", "jira", "crm", "drop"}
EXECUTABLE_KINDS = {
    "next_action",
    "personal_next_action",
    "team_project_work",
    "delegated_work",
    "waiting_for",
    "follow_up",
}
DEFAULT_RULES = {
    "team_project_work": "jira",
    "delegated_work": "jira",
    "next_action": "gtd",
    "personal_next_action": "gtd",
    "waiting_for": "gtd",
    "follow_up": "gtd",
    "crm_record_update": "crm",
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _normalized(value: object) -> str:
    return re.sub(r"\s+", " ", _text(value).casefold())


def stable_action_id(item: dict) -> str:
    """Return a retry-stable identifier from scope, source identity, and action text."""
    source = item.get("source") or {}
    identity = "|".join(
        (
            _normalized(item.get("scope_id")),
            _normalized(source.get("provider") or item.get("source_provider")),
            _normalized(source.get("id") or item.get("source_id")),
            _normalized(item.get("title") or item.get("action")),
        )
    )
    return "close-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _configured_destinations(profile: dict) -> set[str]:
    modules = profile.get("modules") or {}
    routing = modules.get("action-routing") or {}
    configured = set()
    for destination, module_id in (routing.get("destinations") or {}).items():
        if destination in DESTINATIONS and (modules.get(module_id) or {}).get("enabled"):
            configured.add(destination)
    return configured


def _routing_rules(profile: dict) -> dict[str, str]:
    configured = ((profile.get("modules") or {}).get("action-routing") or {}).get("rules") or {}
    return {**DEFAULT_RULES, **configured}


def infer_primary_destination(
    item: dict, configured: set[str], rules: dict[str, str] | None = None
) -> str | None:
    explicit = _text(item.get("primary_destination")).casefold()
    if explicit:
        return explicit if explicit in DESTINATIONS else None
    kind = _text(item.get("action_kind") or item.get("kind") or "next_action").casefold()
    active_rules = rules or DEFAULT_RULES
    if (
        item.get("team_work")
        or item.get("multi_step")
        or item.get("delegated")
        or item.get("acceptance_criteria")
    ):
        preferred = active_rules.get("team_project_work", "jira")
    else:
        preferred = active_rules.get(kind)
    if preferred in configured:
        return preferred
    if preferred == "drop":
        return "drop"
    if preferred == "jira" and "gtd" in configured:
        return "gtd"
    return preferred if preferred in configured else None


def prepare_action_proposal(items: Iterable[dict], profile: dict) -> dict:
    """Create a proposal with one primary destination and linked secondary records."""
    configured = _configured_destinations(profile)
    rules = _routing_rules(profile)
    proposed = []
    unresolved = []
    rejected = []
    seen: set[str] = set()
    for raw in items:
        item = dict(raw)
        action_id = _text(item.get("close_action_id")) or stable_action_id(item)
        if action_id in seen:
            continue
        seen.add(action_id)
        title = _text(item.get("title") or item.get("action"))
        scope_id = _text(item.get("scope_id"))
        kind = _text(item.get("action_kind") or item.get("kind") or "next_action").casefold()
        primary = infer_primary_destination(item, configured, rules)
        if not title or not scope_id or not primary:
            unresolved.append(
                {
                    **item,
                    "close_action_id": action_id,
                    "reason": "title, scope_id, and a configured primary destination are required",
                }
            )
            continue
        if primary == "crm" and (kind in EXECUTABLE_KINDS or item.get("requires_execution")):
            rejected.append(
                {
                    **item,
                    "close_action_id": action_id,
                    "reason": "CRM cannot be the sole home for executable work",
                }
            )
            continue
        secondary = []
        if item.get("crm_applicable") and "crm" in configured and primary != "crm":
            secondary.append(
                {
                    "destination": "crm",
                    "relationship": "linked_record",
                    "linked_to": action_id,
                }
            )
        proposed.append(
            {
                **item,
                "title": title,
                "scope_id": scope_id,
                "action_kind": kind,
                "close_action_id": action_id,
                "external_key": f"close-day:{action_id}",
                "primary_destination": primary,
                "secondary_records": secondary,
            }
        )
    return {
        "contract_version": 1,
        "overlap_policy": "primary_with_links",
        "rules": rules,
        "items": proposed,
        "unresolved": unresolved,
        "rejected": rejected,
        "requires_resolution": bool(unresolved or rejected),
    }


def validate_action_proposal(proposal: dict, profile: dict, approved_ids: Iterable[str] = ()) -> list[str]:
    """Validate exact approval, scope, permission, and destination invariants."""
    errors = []
    scopes = {scope.get("id") for scope in profile.get("scopes") or []}
    configured = _configured_destinations(profile)
    permissions = profile.get("permissions") or {}
    approved = set(approved_ids)
    seen: set[str] = set()
    if proposal.get("items") and not approved:
        errors.append("exact approved action ids are required")
    for index, item in enumerate(proposal.get("items") or []):
        label = f"items[{index}]"
        action_id = _text(item.get("close_action_id"))
        destination = _text(item.get("primary_destination")).casefold()
        kind = _text(item.get("action_kind")).casefold()
        if not action_id:
            errors.append(f"{label}.close_action_id is required")
        elif action_id in seen:
            errors.append(f"duplicate close_action_id: {action_id}")
        else:
            seen.add(action_id)
        if item.get("scope_id") not in scopes:
            errors.append(f"{label}.scope_id must reference a configured scope")
        if destination not in configured and destination != "drop":
            errors.append(f"{label}.primary_destination is not configured: {destination}")
        if destination == "crm" and (kind in EXECUTABLE_KINDS or item.get("requires_execution")):
            errors.append(f"{label}: CRM cannot be the sole home for executable work")
        if destination == "jira" and not permissions.get("jira_writes_enabled", False):
            errors.append(f"{label}: permissions.jira_writes_enabled is false")
        if destination == "gtd" and not permissions.get("gtd_writes_enabled", False):
            errors.append(f"{label}: permissions.gtd_writes_enabled is false")
        if destination == "crm" and not permissions.get("crm_writes_enabled", False):
            errors.append(f"{label}: permissions.crm_writes_enabled is false")
        if action_id not in approved:
            errors.append(f"{label}: exact action approval is missing")
        for link in item.get("secondary_records") or []:
            if link.get("relationship") != "linked_record" or link.get("linked_to") != action_id:
                errors.append(f"{label}: secondary records must link to their primary action")
    if proposal.get("unresolved") or proposal.get("rejected"):
        errors.append("proposal contains unresolved or rejected actions")
    return errors


def build_execution_plan(proposal: dict) -> list[dict]:
    """Return ordered primary writes and dependent links for partial-failure-safe execution."""
    plan = []
    for item in proposal.get("items") or []:
        action_id = item["close_action_id"]
        primary_key = f"primary:{action_id}"
        if item.get("primary_destination") == "drop":
            continue
        plan.append(
            {
                "operation_key": primary_key,
                "destination": item.get("primary_destination"),
                "close_action_id": action_id,
                "external_key": item.get("external_key"),
            }
        )
        for link in item.get("secondary_records") or []:
            plan.append(
                {
                    "operation_key": f"link:{link.get('destination')}:{action_id}",
                    "destination": link.get("destination"),
                    "close_action_id": action_id,
                    "depends_on": primary_key,
                    "relationship": "linked_record",
                }
            )
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or validate close-day action routing.")
    parser.add_argument("command", choices=("prepare", "validate"))
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
    if args.command == "prepare":
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("prepare input must be an array or an object with an items array")
        result = prepare_action_proposal(items, profile)
        exit_code = 2 if result["requires_resolution"] else 0
    else:
        validation_errors = validate_action_proposal(payload, profile, args.approved_id)
        result = {"valid": not validation_errors, "errors": validation_errors}
        exit_code = 1 if validation_errors else 0
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        atomic_write_text(Path(args.output).expanduser(), rendered)
    else:
        sys.stdout.write(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
