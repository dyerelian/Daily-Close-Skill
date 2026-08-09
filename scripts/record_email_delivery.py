#!/usr/bin/env python3
"""Record close-day email delivery state without storing provider identifiers."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from close_day_config import atomic_write_json, load_json


ALLOWED_STATUSES = {"pending", "sent", "failed"}


def record_delivery(state: dict, envelope: dict, status: str, error: str | None = None) -> dict:
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
    record = {
        "status": status,
        "delivery_key": delivery_key,
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "from": envelope.get("from"),
        "recipients": envelope.get("recipients") or [],
        "subject": envelope.get("subject"),
        "attachments": [Path(path).name for path in (envelope.get("attachment_files") or [])],
    }
    if status == "failed" and error:
        record["error"] = error[:500]
    delivery["email"] = record
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Record close-day email delivery status.")
    parser.add_argument("--state", required=True, help="Close-state JSON path.")
    parser.add_argument("--envelope", required=True, help="Prepared email-envelope JSON path.")
    parser.add_argument("--status", choices=sorted(ALLOWED_STATUSES), required=True)
    parser.add_argument("--error", help="Failure summary; provider identifiers must not be included.")
    parser.add_argument("--approved", action="store_true", help="Required to update close state.")
    args = parser.parse_args()
    if not args.approved:
        parser.error("state update requires --approved")
    state_path = Path(args.state).expanduser()
    state = load_json(state_path)
    envelope = load_json(Path(args.envelope).expanduser())
    updated = record_delivery(state, envelope, args.status, args.error)
    atomic_write_json(state_path, updated)
    print(json.dumps({"state": str(state_path), "status": args.status}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
