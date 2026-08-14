#!/usr/bin/env python3
"""Prepare and validate deterministic delegated CRM review handoffs."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from close_day_config import atomic_write_json, load_json, resolve_profile, resolved_artifact_paths


CONTRACT_VERSION = 1
FINAL_REVIEW_STATUS = "completed"
CHANGE_OPERATIONS = {"add_row", "update_cells"}
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def timezone_for(timezone_name: str, fallback=None):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name.upper() in {"UTC", "ETC/UTC"}:
            return timezone.utc
        return fallback or datetime.now().astimezone().tzinfo


def parse_datetime(value: str, timezone_name: str) -> datetime:
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        parsed_date = date.fromisoformat(value)
        parsed = datetime.combine(parsed_date, time.max)
    else:
        parsed = datetime.fromisoformat(value)
    zone = timezone_for(timezone_name, parsed.tzinfo)
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)


def latest_reviewed_through(
    state_dir: Path,
    profile_id: str,
    scope_ids: set[str],
    not_after: datetime | None = None,
) -> datetime | None:
    latest: datetime | None = None
    if not state_dir.is_dir():
        return None
    for path in state_dir.glob("*-close.json"):
        try:
            payload = load_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        review = payload.get("crm_review") or {}
        if review.get("status") != FINAL_REVIEW_STATUS:
            continue
        if review.get("profile_id") not in (None, profile_id):
            continue
        recorded_scopes = set(review.get("scope_ids") or [])
        if recorded_scopes and recorded_scopes != scope_ids:
            continue
        value = review.get("reviewed_through") or ((review.get("window") or {}).get("end"))
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            continue
        if not_after is not None and parsed > not_after:
            continue
        latest = parsed if latest is None or parsed > latest else latest
    return latest


def evidence_items(payload: Any, scope_ids: set[str]) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("classified"), list):
        candidates = payload["classified"]
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        candidates = payload["items"]
    elif isinstance(payload, list):
        candidates = payload
    else:
        raise ValueError("evidence must be a list or contain items/classified")

    result: list[dict] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("status") in {"excluded", "unclassified"}:
            continue
        item = candidate.get("item") if isinstance(candidate.get("item"), dict) else candidate
        scope_id = candidate.get("scope_id") or item.get("scope_id")
        if scope_id not in scope_ids:
            continue
        normalized = dict(item)
        normalized["scope_id"] = scope_id
        source = normalized.get("source") or {}
        stable_id = str(source.get("id") or normalized.get("id") or canonical_hash(normalized))
        provider = str(source.get("provider") or "unknown")
        key = f"{provider}:{stable_id}"
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return sorted(
        result,
        key=lambda item: (
            str(item.get("timestamp") or ""),
            str((item.get("source") or {}).get("provider") or ""),
            str((item.get("source") or {}).get("id") or item.get("id") or ""),
        ),
    )


def prepare_request(
    profile: dict,
    routed_evidence: Any,
    close_at: datetime,
    state_dir: Path | None = None,
) -> dict:
    module = ((profile.get("modules") or {}).get("crm-google-sheet") or {})
    if not module.get("enabled"):
        raise ValueError("crm-google-sheet is not enabled")
    if module.get("mode", "portable_workbook") != "delegated_handler":
        raise ValueError("CRM handoffs require mode delegated_handler")

    timezone_name = str((profile.get("owner") or {}).get("timezone") or "UTC")
    zone = timezone_for(timezone_name, close_at.tzinfo)
    close_at = close_at.replace(tzinfo=zone) if close_at.tzinfo is None else close_at.astimezone(zone)
    scope_ids = set(module.get("scope_ids") or [])
    profile_id = str((profile.get("profile") or {}).get("id") or "default")
    first_days = int(module.get("first_run_lookback_days", 14))
    overlap_hours = int(module.get("overlap_hours", 24))
    if state_dir is None:
        state_dir = Path(resolved_artifact_paths(profile["artifacts"])["state"])
    prior = latest_reviewed_through(state_dir, profile_id, scope_ids, close_at)
    first_run = prior is None
    window_start = close_at - timedelta(days=first_days) if first_run else prior - timedelta(hours=overlap_hours)

    scoped_evidence = []
    for item in evidence_items(routed_evidence, scope_ids):
        timestamp_value = item.get("timestamp") or ((item.get("source") or {}).get("timestamp"))
        if timestamp_value:
            try:
                item_time = parse_datetime(str(timestamp_value), timezone_name)
            except ValueError:
                continue
            if item_time < window_start or item_time > close_at:
                continue
        scoped_evidence.append(item)

    policy = {
        "allow_new_rows": bool(module.get("allow_new_rows", False)),
        "minimum_confidence": module.get("minimum_confidence", "high"),
        "allow_live_sheet_writes": bool(module.get("allow_live_sheet_writes", False)),
        "approval_mode": "consolidated_close",
        "roll_weekly_jira": bool(module.get("roll_weekly_jira", False)),
    }
    request = {
        "contract_version": CONTRACT_VERSION,
        "mode": "close_day_incremental",
        "profile_id": profile_id,
        "scope_ids": sorted(scope_ids),
        "handler_skill": module.get("handler_skill"),
        "window": {
            "start": window_start.isoformat(),
            "end": close_at.isoformat(),
            "timezone": timezone_name,
            "first_run": first_run,
            "overlap_hours": overlap_hours,
        },
        "policy": policy,
        "evidence": scoped_evidence,
    }
    request["request_id"] = canonical_hash(request)
    return request


def change_identity(request_id: str, change: dict) -> dict:
    return {
        "request_id": request_id,
        "scope_id": change.get("scope_id"),
        "operation": change.get("operation"),
        "row": change.get("row") or {},
        "cells": change.get("cells") or [],
        "confidence": change.get("confidence"),
        "inferred": change.get("inferred"),
        "evidence_refs": change.get("evidence_refs") or [],
        "rationale": change.get("rationale"),
    }


def normalize_proposal(request: dict, proposal: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    if request.get("contract_version") != CONTRACT_VERSION:
        errors.append("request contract_version is unsupported")
    if proposal.get("contract_version") != CONTRACT_VERSION:
        errors.append("proposal contract_version is unsupported")
    if proposal.get("request_id") != request.get("request_id"):
        errors.append("proposal request_id does not match the request")
    source_coverage = proposal.get("source_coverage")
    if not isinstance(source_coverage, list):
        errors.append("proposal source_coverage must be an array")
    else:
        for index, source in enumerate(source_coverage):
            if not isinstance(source, dict) or not str(source.get("source") or "").strip():
                errors.append(f"source_coverage[{index}] must name a source")
            elif not str(source.get("status") or "").strip():
                errors.append(f"source_coverage[{index}] must include status")
    if not isinstance(proposal.get("gaps", []), list):
        errors.append("proposal gaps must be an array")
    review_flags = proposal.get("review_flags", [])
    if not isinstance(review_flags, list):
        errors.append("proposal review_flags must be an array")
    else:
        allowed_scopes = set(request.get("scope_ids") or [])
        for index, flag in enumerate(review_flags):
            label = f"review_flags[{index}]"
            if not isinstance(flag, dict) or not str(flag.get("text") or "").strip():
                errors.append(f"{label} must contain non-empty text")
                continue
            if flag.get("scope_id") not in allowed_scopes:
                errors.append(f"{label}.scope_id must be permitted by the request")
    derived_follow_ups = proposal.get("derived_follow_ups", [])
    if not isinstance(derived_follow_ups, list):
        errors.append("proposal derived_follow_ups must be an array")
    else:
        allowed_scopes = set(request.get("scope_ids") or [])
        for index, follow_up in enumerate(derived_follow_ups):
            label = f"derived_follow_ups[{index}]"
            if not isinstance(follow_up, dict) or not str(follow_up.get("text") or "").strip():
                errors.append(f"{label} must contain non-empty text")
                continue
            if follow_up.get("scope_id") not in allowed_scopes:
                errors.append(f"{label}.scope_id must be permitted by the request")

    changes = proposal.get("changes")
    if not isinstance(changes, list):
        errors.append("proposal changes must be an array")
        changes = []
    minimum = str((request.get("policy") or {}).get("minimum_confidence") or "high")
    normalized_changes: list[dict] = []
    seen: set[str] = set()
    for index, raw_change in enumerate(changes):
        label = f"changes[{index}]"
        if not isinstance(raw_change, dict):
            errors.append(f"{label} must be an object")
            continue
        change = dict(raw_change)
        if change.get("scope_id") not in set(request.get("scope_ids") or []):
            errors.append(f"{label}.scope_id must be permitted by the request")
        operation = change.get("operation")
        if operation not in CHANGE_OPERATIONS:
            errors.append(f"{label}.operation must be add_row or update_cells")
        row = change.get("row")
        if not isinstance(row, dict) or not any(
            str(row.get(key) or "").strip() for key in ("email", "company", "contact_name")
        ):
            errors.append(f"{label}.row must identify a company, contact, or email")
        cells = change.get("cells")
        if not isinstance(cells, list) or not cells:
            errors.append(f"{label}.cells must be a non-empty array")
        else:
            seen_columns: set[str] = set()
            for cell_index, cell in enumerate(cells):
                if not isinstance(cell, dict) or not str(cell.get("column") or "").strip():
                    errors.append(f"{label}.cells[{cell_index}] must name a column")
                    continue
                column = str(cell["column"]).casefold()
                if column in seen_columns:
                    errors.append(f"{label}.cells[{cell_index}] duplicates a column")
                seen_columns.add(column)
                if "old" not in cell or "new" not in cell:
                    errors.append(f"{label}.cells[{cell_index}] must include old and new")
        confidence = str(change.get("confidence") or "").lower()
        if confidence not in CONFIDENCE_ORDER:
            errors.append(f"{label}.confidence must be low, medium, or high")
        elif confidence == "low" or CONFIDENCE_ORDER[confidence] < CONFIDENCE_ORDER.get(minimum, 2):
            errors.append(f"{label}.confidence is below the configured proposal threshold")
        if not isinstance(change.get("inferred"), bool):
            errors.append(f"{label}.inferred must be a boolean")
        if not isinstance(change.get("evidence_refs"), list) or not change.get("evidence_refs"):
            errors.append(f"{label}.evidence_refs must be a non-empty array")
        if not str(change.get("rationale") or "").strip():
            errors.append(f"{label}.rationale must be non-empty")
        change_id = canonical_hash(change_identity(str(request.get("request_id")), change))
        if change.get("change_id") not in (None, change_id):
            errors.append(f"{label}.change_id is not deterministic")
        change["change_id"] = change_id
        if change_id in seen:
            errors.append(f"{label} duplicates an earlier change")
        seen.add(change_id)
        normalized_changes.append(change)

    normalized = dict(proposal)
    normalized["changes"] = normalized_changes
    normalized["handler_skill"] = request.get("handler_skill")
    normalized["mode"] = request.get("mode")
    normalized["scope_ids"] = request.get("scope_ids")
    if (request.get("policy") or {}).get("roll_weekly_jira"):
        errors.append("close_day_incremental requests must not roll the weekly Jira task")
    return normalized, errors


def build_review_state(request: dict, proposal: dict, outcome: dict) -> tuple[dict, list[str]]:
    normalized, errors = normalize_proposal(request, proposal)
    status = outcome.get("status")
    if status not in {"completed", "failed"}:
        errors.append("outcome status must be completed or failed")

    outcome_gaps = outcome.get("gaps", [])
    if not isinstance(outcome_gaps, list) or any(
        not isinstance(item, str) or not item.strip() for item in outcome_gaps
    ):
        errors.append("outcome gaps must be an array of non-empty strings")
        outcome_gaps = []

    allowed_scopes = set(request.get("scope_ids") or [])

    def scoped_outcome_items(key: str) -> list[dict]:
        value = outcome.get(key, [])
        if not isinstance(value, list):
            errors.append(f"outcome {key} must be an array")
            return []
        valid: list[dict] = []
        for index, item in enumerate(value):
            label = f"outcome {key}[{index}]"
            if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                errors.append(f"{label} must contain non-empty text")
                continue
            if item.get("scope_id") not in allowed_scopes:
                errors.append(f"{label}.scope_id must be permitted by the request")
                continue
            valid.append(item)
        return valid

    summary_items = scoped_outcome_items("summary_items")
    outcome_review_flags = scoped_outcome_items("review_flags")

    proposal_ids = {change["change_id"] for change in normalized.get("changes") or []}
    decisions: dict[str, set[str]] = {}
    for key in ("approved_change_ids", "applied_change_ids", "rejected_change_ids"):
        value = outcome.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"outcome {key} must be an array of strings")
            decisions[key] = set()
            continue
        decisions[key] = set(value)
        unknown = decisions[key] - proposal_ids
        if unknown:
            errors.append(f"outcome {key} contains unknown change ids")
    approved = decisions["approved_change_ids"]
    applied = decisions["applied_change_ids"]
    rejected = decisions["rejected_change_ids"]
    if approved & rejected:
        errors.append("a change id cannot be both approved and rejected")
    if applied - approved:
        errors.append("applied change ids must be approved")
    if status == "completed":
        if approved != applied:
            errors.append("completed outcome requires every approved change to be applied")
        if approved | rejected != proposal_ids:
            errors.append("completed outcome requires a decision for every proposed change")
    elif status == "failed" and not str(outcome.get("failure") or "").strip() and not outcome_gaps:
        errors.append("failed outcome must include failure or gaps")

    state = {
        "status": status,
        "handler_skill": request.get("handler_skill"),
        "profile_id": request.get("profile_id"),
        "scope_ids": request.get("scope_ids") or [],
        "request_id": request.get("request_id"),
        "window": request.get("window") or {},
        "source_coverage": normalized.get("source_coverage") or [],
        "gaps": [*(normalized.get("gaps") or []), *outcome_gaps],
        "approved_change_ids": sorted(approved),
        "applied_change_ids": sorted(applied),
        "rejected_change_ids": sorted(rejected),
        "counts": {
            "proposed": len(proposal_ids),
            "approved": len(approved),
            "applied": len(applied),
            "rejected": len(rejected),
        },
        "summary_items": summary_items,
        "review_flags": [
            *(normalized.get("review_flags") or []),
            *outcome_review_flags,
        ],
    }
    if status == "completed":
        state["reviewed_through"] = ((request.get("window") or {}).get("end"))
    elif outcome.get("failure"):
        state["failure"] = str(outcome["failure"])[:500]
    return state, errors


def load_profile(args: argparse.Namespace) -> dict:
    if args.profile_file:
        return load_json(Path(args.profile_file).expanduser())
    profile, _ = resolve_profile(
        args.profile,
        Path(args.config_root).expanduser() if args.config_root else None,
    )
    return profile


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or validate delegated CRM review JSON.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="Prepare a scoped CRM review request.")
    prepare_parser.add_argument("--evidence", required=True)
    prepare_parser.add_argument("--profile")
    prepare_parser.add_argument("--profile-file")
    prepare_parser.add_argument("--config-root")
    prepare_parser.add_argument("--close-at", required=True, help="ISO date or datetime.")
    prepare_parser.add_argument("--state-dir")
    prepare_parser.add_argument("--output")

    validate_parser = subparsers.add_parser(
        "validate-proposal", help="Validate and normalize a handler proposal."
    )
    validate_parser.add_argument("--request", required=True)
    validate_parser.add_argument("--proposal", required=True)
    validate_parser.add_argument("--output")

    state_parser = subparsers.add_parser(
        "build-state", help="Build compact close-state data from a decided CRM proposal."
    )
    state_parser.add_argument("--request", required=True)
    state_parser.add_argument("--proposal", required=True)
    state_parser.add_argument("--outcome", required=True)
    state_parser.add_argument("--output")

    args = parser.parse_args()
    if args.command == "prepare":
        profile = load_profile(args)
        timezone_name = str((profile.get("owner") or {}).get("timezone") or "UTC")
        request = prepare_request(
            profile,
            load_json(Path(args.evidence).expanduser()),
            parse_datetime(args.close_at, timezone_name),
            Path(args.state_dir).expanduser() if args.state_dir else None,
        )
        if args.output:
            atomic_write_json(Path(args.output).expanduser(), request)
        print(json.dumps(request, ensure_ascii=False, indent=2))
        return 0

    request = load_json(Path(args.request).expanduser())
    proposal = load_json(Path(args.proposal).expanduser())
    if args.command == "build-state":
        normalized, errors = build_review_state(
            request,
            proposal,
            load_json(Path(args.outcome).expanduser()),
        )
    else:
        normalized, errors = normalize_proposal(request, proposal)
    if errors:
        print(json.dumps({"errors": errors}, indent=2))
        return 1
    if args.output:
        atomic_write_json(Path(args.output).expanduser(), normalized)
    print(json.dumps(normalized, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
