#!/usr/bin/env python3
"""Prepare a deterministic close-day email envelope without sending it."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from close_day_config import (
    atomic_write_json,
    load_json,
    resolve_profile,
    resolved_artifact_paths,
    validate_profile,
)


def clean_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or value.get("title") or value.get("subject") or "").strip()
    return str(value or "").strip()


def concise_body(payload: dict, target_date: str) -> str:
    lines = [f"Here is your Daily Success Plan for {target_date}."]
    summary = clean_text(payload.get("summary"))
    if summary:
        lines.extend(["", summary])
    priorities = [
        clean_text(item)
        for item in ((payload.get("sections") or {}).get("priorities") or [])
        if clean_text(item)
    ]
    if priorities:
        lines.extend(["", "Top priorities:"])
        lines.extend(f"- {item}" for item in priorities[:3])
    lines.extend(["", "The complete Daily Plan is attached as a Word document."])
    return "\n".join(lines)


def prepare_email(
    payload: dict,
    profile: dict,
    require_attachments: bool = True,
    allow_failed_retry: bool = False,
) -> dict:
    errors, _ = validate_profile(profile)
    if errors:
        raise ValueError("invalid profile: " + "; ".join(errors))
    module = ((profile.get("modules") or {}).get("email-delivery") or {})
    if not module.get("enabled"):
        raise ValueError("email-delivery is not enabled")
    if not (profile.get("permissions") or {}).get("email_delivery_enabled", False):
        raise PermissionError("profile does not permit email delivery")
    if not module.get("connector_configured", False):
        raise RuntimeError("Gmail connector is not marked configured")

    target_date = date.fromisoformat(
        str(payload.get("target_date") or payload.get("date") or date.today().isoformat())
    ).isoformat()
    subject = str(module["subject_template"]).format(target_date=target_date).strip()
    paths = {key: Path(value) for key, value in resolved_artifact_paths(profile["artifacts"]).items()}
    attachment_files: list[str] = []
    for attachment in module.get("attachments") or []:
        if attachment == "daily_plan_docx":
            attachment_files.append(str(paths["plans"] / f"Daily Plan {target_date}.docx"))
    missing = [path for path in attachment_files if not Path(path).is_file()]
    if require_attachments and missing:
        raise FileNotFoundError("email attachment does not exist: " + ", ".join(missing))

    if module.get("body_style") == "full_plan":
        plan_path = paths["plans"] / f"Daily Plan {target_date}.md"
        if not plan_path.is_file():
            raise FileNotFoundError(f"email body source does not exist: {plan_path}")
        body = plan_path.read_text(encoding="utf-8")
    else:
        body = concise_body(payload, target_date)

    identity = {
        "profile_id": (profile.get("profile") or {}).get("id"),
        "target_date": target_date,
        "from": module["from"],
        "recipients": module["recipients"],
        "subject": subject,
        "body": body,
        "attachment_files": attachment_files,
        "mode": module["mode"],
    }
    delivery_key = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    prior = (((payload.get("delivery") or {}).get("email")) or {})
    prior_status = prior.get("status") if prior.get("delivery_key") == delivery_key else None
    if prior_status == "sent":
        status = "already_sent"
    elif prior_status == "pending":
        status = "pending_review"
    elif prior_status == "failed" and not allow_failed_retry:
        status = "failed_requires_retry"
    else:
        status = "ready"
    return {
        "status": status,
        "send": status == "ready",
        "action": "send" if module["mode"] == "send_after_approved_close" else "draft",
        "delivery_key": delivery_key,
        "connector": module["connector"],
        "from": module["from"],
        "to": ", ".join(module["recipients"]),
        "recipients": module["recipients"],
        "mode": module["mode"],
        "subject": subject,
        "body": body,
        "content_type": "text/markdown",
        "attachment_files": attachment_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a finalized close-day email envelope.")
    parser.add_argument("--input", required=True, help="Approved close/state JSON.")
    parser.add_argument("--profile", help="Profile id from the local registry.")
    parser.add_argument("--profile-file", help="Explicit schema-v2 profile JSON path.")
    parser.add_argument("--config-root", help="Override the private config directory.")
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument(
        "--allow-missing-attachments",
        action="store_true",
        help="Permit envelope preview before the configured attachment exists.",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Explicitly retry a matching delivery previously recorded as failed.",
    )
    args = parser.parse_args()
    if args.profile_file:
        profile = load_json(Path(args.profile_file).expanduser())
    else:
        profile, _ = resolve_profile(
            args.profile, Path(args.config_root).expanduser() if args.config_root else None
        )
    payload = load_json(Path(args.input).expanduser())
    envelope = prepare_email(
        payload,
        profile,
        not args.allow_missing_attachments,
        allow_failed_retry=args.retry_failed,
    )
    if args.output:
        atomic_write_json(Path(args.output).expanduser(), envelope)
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
