#!/usr/bin/env python3
"""Record close-day email delivery state without storing provider identifiers."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from close_day_config import atomic_write_json, load_json


ALLOWED_STATUSES = {"approved", "pending", "sent", "failed"}
ERROR_CATEGORIES = {
    "workspace_policy",
    "authentication",
    "transient",
    "ambiguous",
    "provider",
}


def classify_delivery_error(error: str | None) -> str:
    message = (error or "").lower()
    if "workspace admin" in message or (
        "payload" in message and ("schema" in message or "required" in message)
    ):
        return "workspace_policy"
    if any(term in message for term in ("authentication", "authorization", "oauth", "scope")):
        return "authentication"
    if any(term in message for term in ("timeout", "rate limit", "temporar", "unavailable")):
        return "transient"
    if any(term in message for term in ("ambiguous", "unknown delivery", "delivery uncertain")):
        return "ambiguous"
    return "provider"


def record_delivery(
    state: dict,
    envelope: dict,
    status: str,
    error: str | None = None,
    error_category: str | None = None,
) -> dict:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(ALLOWED_STATUSES))}")
    delivery_key = envelope.get("delivery_key")
    if not isinstance(delivery_key, str) or not delivery_key:
        raise ValueError("envelope.delivery_key must be a non-empty string")
    delivery = state.setdefault("delivery", {})
    existing = delivery.get("email") or {}
    if existing.get("status") == "sent" and existing.get("delivery_key") == delivery_key:
        if status == "sent":
            return state
        raise ValueError("email is already recorded as sent for this delivery key")
    if error_category is not None and error_category not in ERROR_CATEGORIES:
        raise ValueError(
            "error_category must be one of: " + ", ".join(sorted(ERROR_CATEGORIES))
        )

    recorded_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    same_delivery = existing.get("delivery_key") == delivery_key
    approved_at = (
        existing.get("approved_at")
        if same_delivery and existing.get("approved_delivery_key") == delivery_key
        else None
    )
    if status == "approved" and not approved_at:
        approved_at = recorded_at
    attempt_count = int(existing.get("attempt_count") or 0) if same_delivery else 0
    if status == "pending":
        attempt_count += 1

    record = {
        "status": status,
        "delivery_key": delivery_key,
        "recorded_at": recorded_at,
        "from": envelope.get("from"),
        "recipients": envelope.get("recipients") or [],
        "subject": envelope.get("subject"),
        "attachments": [Path(path).name for path in (envelope.get("attachment_files") or [])],
        "attempt_count": attempt_count,
    }
    if approved_at:
        record["approved_delivery_key"] = delivery_key
        record["approved_at"] = approved_at
    if status == "failed" and error:
        record["error"] = error[:500]
        record["error_category"] = error_category or classify_delivery_error(error)
    delivery["email"] = record
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Record close-day email delivery status.")
    parser.add_argument("--state", required=True, help="Close-state JSON path.")
    parser.add_argument("--envelope", required=True, help="Prepared email-envelope JSON path.")
    parser.add_argument("--status", choices=sorted(ALLOWED_STATUSES), required=True)
    parser.add_argument("--error", help="Failure summary; provider identifiers must not be included.")
    parser.add_argument("--error-category", choices=sorted(ERROR_CATEGORIES))
    parser.add_argument("--approved", action="store_true", help="Required to update close state.")
    args = parser.parse_args()
    if not args.approved:
        parser.error("state update requires --approved")
    state_path = Path(args.state).expanduser()
    state = load_json(state_path)
    envelope = load_json(Path(args.envelope).expanduser())
    updated = record_delivery(
        state,
        envelope,
        args.status,
        args.error,
        args.error_category,
    )
    atomic_write_json(state_path, updated)
    print(json.dumps({"state": str(state_path), "status": args.status}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
