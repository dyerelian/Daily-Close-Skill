#!/usr/bin/env python3
"""Build a provider-neutral CRM proposal from normalized email evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from close_day_config import atomic_write_json
from propose_crm_from_gmail import build_proposal


def normalized_email_payload(data: object) -> object:
    """Translate the close-day evidence contract into the legacy email proposal shape."""
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        values = data["items"]
    elif isinstance(data, list):
        values = data
    else:
        return data
    emails = []
    for item in values:
        if not isinstance(item, dict) or item.get("kind") not in {None, "message"}:
            continue
        source = item.get("source") or {}
        participants = item.get("participants") or []
        sender = item.get("from") or item.get("from_")
        if not sender and participants:
            sender = participants[0]
        emails.append({
            "id": item.get("id") or source.get("id"),
            "thread_id": item.get("thread_id"),
            "subject": item.get("subject") or item.get("title"),
            "snippet": item.get("snippet") or item.get("text"),
            "from_": sender or source.get("account") or "",
            "to": item.get("to") or "",
            "email_ts": item.get("timestamp"),
            "display_url": item.get("link") or source.get("link"),
        })
    return emails


def main() -> int:
    parser = argparse.ArgumentParser(description="Create CRM proposal JSON from normalized mail evidence.")
    parser.add_argument("--input", required=True, help="Normalized Gmail or Outlook mail payload JSON.")
    parser.add_argument("--out", required=True, help="Proposal JSON output path.")
    parser.add_argument("--owner-email", default="user@example.com")
    parser.add_argument("--provider", choices=("gmail", "outlook", "mixed"), default="mixed")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()
    try:
        with Path(args.input).expanduser().open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        proposal = build_proposal(normalized_email_payload(data), args.owner_email, args.dry_run)
        proposal["source"] = args.provider
        proposal["confidence_notes"] = [
            note.replace("Gmail", "mail provider") for note in proposal.get("confidence_notes") or []
        ]
        atomic_write_json(Path(args.out).expanduser(), proposal)
        print(f"wrote: {Path(args.out).expanduser()}")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
