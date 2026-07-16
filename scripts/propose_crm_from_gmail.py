#!/usr/bin/env python3
"""Build dry-run CRM update proposals from Gmail search/read payloads."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")

ACCOUNT_HINTS = {
    "active_customer_program": {
        "account": "Example Customer Program",
        "relationship_type": "Customer/Program",
        "stage": "Active Program",
        "status": "Active",
        "priority": "P1 - Must",
    },
    "active_opportunity_customer_pursuit": {
        "account": "Example Opportunity",
        "relationship_type": "Opportunity",
        "stage": "Pursuit",
        "status": "Active",
        "priority": "P1 - Must",
    },
    "active_research_customer_collaboration": {
        "account": "Example Research Collaboration",
        "relationship_type": "Research/Customer Collaboration",
        "stage": "Active Collaboration",
        "status": "Active",
        "priority": "P2 - Should",
    },
    "award_program_onboarding": {
        "account": "Example Award Program",
        "relationship_type": "Award/Program",
        "stage": "Award Onboarding",
        "status": "Active",
        "priority": "P1 - Must",
    },
    "partner_ecosystem_relationship": {
        "account": "Example Ecosystem Partner",
        "relationship_type": "Partner/Ecosystem",
        "stage": "Partner Pipeline",
        "status": "Active",
        "priority": "P2 - Should",
    },
    "partner_led_pipeline": {
        "account": "Example Partner-Led Pipeline",
        "relationship_type": "Partner-led Pipeline",
        "stage": "Partner Pipeline",
        "status": "Active",
        "priority": "P2 - Should",
    },
}

KEYWORD_HINTS = [
    ("CUSTOMER", "active_customer_program"),
    ("PROGRAM", "active_customer_program"),
    ("OPPORTUNITY", "active_opportunity_customer_pursuit"),
    ("PILOT", "active_opportunity_customer_pursuit"),
    ("RESEARCH", "active_research_customer_collaboration"),
    ("COLLABORATION", "active_research_customer_collaboration"),
    ("AWARD", "award_program_onboarding"),
    ("ONBOARDING", "award_program_onboarding"),
    ("ECOSYSTEM", "partner_ecosystem_relationship"),
    ("PARTNER", "partner_ecosystem_relationship"),
    ("PIPELINE", "partner_led_pipeline"),
    ("CONFERENCE", "partner_led_pipeline"),
]

REQUEST_TERMS = (
    "?",
    "please",
    "could you",
    "can you",
    "would you",
    "confirm",
    "share",
    "send",
    "review",
    "let me know",
    "follow up",
    "available",
    "do you have",
)


def resolve(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def text(value: Any) -> str:
    return "" if value is None else str(value)


def compact(value: str, limit: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3].rstrip() + "..."


def extract_email(value: str) -> str:
    match = EMAIL_RE.search(value or "")
    return match.group(0).lower() if match else ""


def extract_name(value: str) -> str:
    email = extract_email(value)
    name = value.replace(email, "").replace("<", "").replace(">", "").strip()
    name = name.strip('"').strip()
    return name or email


def source_ref(email: dict) -> dict:
    return {
        "message_id": email.get("id") or email.get("message_id"),
        "thread_id": email.get("thread_id"),
        "date": email.get("email_ts") or email.get("date"),
        "subject": email.get("subject"),
        "from": email.get("from_") or email.get("from"),
        "url": email.get("display_url") or email.get("url"),
    }


def flattened_payload(data: Any) -> list[tuple[dict, dict]]:
    pairs: list[tuple[dict, dict]] = []
    if isinstance(data, dict) and isinstance(data.get("queries"), list):
        for query in data["queries"]:
            meta = {
                "category": query.get("category"),
                "account_hint": query.get("account_hint"),
                "query": query.get("query"),
            }
            for email in query.get("emails") or []:
                if isinstance(email, dict):
                    pairs.append((meta, email))
    elif isinstance(data, dict) and isinstance(data.get("emails"), list):
        meta = {
            "category": data.get("category"),
            "account_hint": data.get("account_hint"),
            "query": data.get("query"),
        }
        for email in data["emails"]:
            if isinstance(email, dict):
                pairs.append((meta, email))
    elif isinstance(data, list):
        for email in data:
            if isinstance(email, dict):
                pairs.append(({}, email))
    else:
        raise ValueError("input must contain queries[].emails, emails, or be an email array")
    return pairs


def infer_category(meta: dict, email: dict) -> str:
    if meta.get("category") in ACCOUNT_HINTS:
        return meta["category"]
    combined = f"{email.get('subject', '')} {email.get('snippet', '')} {email.get('from_', '')}".upper()
    for keyword, category in KEYWORD_HINTS:
        if keyword in combined:
            return category
    return "partner_led_pipeline"


def contains_request(email: dict) -> bool:
    combined = f"{email.get('subject', '')} {email.get('snippet', '')}".lower()
    return any(term in combined for term in REQUEST_TERMS)


def is_owner_sender(email: dict, owner_email: str) -> bool:
    sender = email.get("from_") or email.get("from") or ""
    return owner_email.lower() in sender.lower()


def add_contact(
    contact_map: dict,
    account: str,
    raw_person: str,
    role: str,
    date: str,
    evidence: dict,
    owner_email: str,
) -> None:
    email = extract_email(raw_person)
    if not email or email == owner_email.lower():
        return
    entry = contact_map.setdefault(
        email,
        {
            "name": extract_name(raw_person),
            "account": account,
            "role_title": "",
            "email": email,
            "relationship_role": role,
            "last_touch": date[:10] if date else "",
            "follow_up_flag": "No",
            "notes": "",
            "source_refs": [],
        },
    )
    if date and (not entry["last_touch"] or date[:10] > entry["last_touch"]):
        entry["last_touch"] = date[:10]
    if len(entry["source_refs"]) < 3:
        entry["source_refs"].append(evidence)


def build_proposal(data: Any, owner_email: str, dry_run: bool) -> dict:
    pairs = flattened_payload(data)
    accounts: dict[str, dict] = {}
    contacts: dict[str, dict] = {}
    interactions: list[dict] = []
    followups_owner: list[dict] = []
    followups_others: list[dict] = []
    coverage: dict[str, dict] = defaultdict(lambda: {"messages_seen": 0, "messages_used": 0})

    for meta, email in pairs:
        category = infer_category(meta, email)
        hint = ACCOUNT_HINTS[category]
        account = hint["account"]
        ref = source_ref(email)
        date = text(email.get("email_ts") or email.get("date"))
        subject = compact(text(email.get("subject")), 160)
        snippet = compact(text(email.get("snippet")), 260)

        coverage_key = f"{category}|{meta.get('query') or ''}"
        coverage[coverage_key]["category"] = category
        coverage[coverage_key]["query"] = meta.get("query")
        coverage[coverage_key]["account_hint"] = meta.get("account_hint") or account
        coverage[coverage_key]["messages_seen"] += 1
        coverage[coverage_key]["messages_used"] += 1

        account_entry = accounts.setdefault(
            account,
            {
                "account_name": account,
                "relationship_type": hint["relationship_type"],
                "stage": hint["stage"],
                "status": hint["status"],
                "priority": hint["priority"],
                "owner": "Owner",
                "last_touch": "",
                "next_follow_up": "",
                "next_step": "Review Gmail-derived proposal and confirm CRM entry.",
                "source_evidence": [],
                "canonical_page_url": "",
                "confidence": 0.0,
            },
        )
        if date and (not account_entry["last_touch"] or date[:10] > account_entry["last_touch"]):
            account_entry["last_touch"] = date[:10]
        if len(account_entry["source_evidence"]) < 5:
            account_entry["source_evidence"].append(ref)

        role = "Partner" if "Partner" in hint["relationship_type"] else "Customer"
        add_contact(
            contacts,
            account,
            text(email.get("from_") or email.get("from")),
            role,
            date,
            ref,
            owner_email,
        )
        for recipient in (email.get("to") or []) + (email.get("cc") or []):
            add_contact(contacts, account, text(recipient), role, date, ref, owner_email)

        interactions.append(
            {
                "date": date[:10] if date else "",
                "channel": "Gmail",
                "account": account,
                "contacts": "",
                "subject": subject,
                "summary": snippet,
                "action_extracted": "Review for CRM relevance and follow-up.",
                "source_link": ref.get("url"),
                "source_ref": ref,
            }
        )

        if contains_request(email):
            if is_owner_sender(email, owner_email):
                followups_others.append(
                    {
                        "due_date": "",
                        "account": account,
                        "contact": "",
                        "ask_task": f"Await response: {subject}",
                        "owner": "Other",
                        "status": "Waiting",
                        "source_interaction": ref,
                        "confidence": 0.65,
                    }
                )
            else:
                followups_owner.append(
                    {
                        "due_date": "",
                        "account": account,
                        "contact": extract_name(text(email.get("from_") or email.get("from"))),
                        "ask_task": f"Review/respond: {subject}",
                        "owner": "Owner",
                        "status": "Open",
                        "source_interaction": ref,
                        "confidence": 0.7,
                    }
                )

    for entry in accounts.values():
        evidence_count = len(entry["source_evidence"])
        entry["confidence"] = round(min(0.95, 0.45 + 0.1 * evidence_count), 2)
        entry["source_evidence_text"] = json.dumps(entry["source_evidence"], ensure_ascii=False)

    proposal = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "dry_run": dry_run,
        "source": "gmail",
        "owner_email": owner_email,
        "coverage": list(coverage.values()),
        "new_account_candidates": sorted(accounts.values(), key=lambda item: item["account_name"]),
        "new_contact_candidates": sorted(contacts.values(), key=lambda item: (item["account"], item["email"])),
        "interaction_summaries": interactions,
        "followups_owner_owes": followups_owner,
        "followups_others_owe_owner": followups_others,
        "confidence_notes": [
            "Confidence is heuristic and based on query category, keyword match, and source count.",
            "This script does not write to Gmail, Google Sheets, or local CRM files.",
            "Review source message/thread references before approving CRM changes.",
        ],
    }
    return proposal


def main() -> int:
    parser = argparse.ArgumentParser(description="Create CRM proposal JSON from Gmail payload.")
    parser.add_argument("--input", required=True, help="Gmail search/read payload JSON.")
    parser.add_argument("--out", required=True, help="Proposal JSON output path.")
    parser.add_argument("--owner-email", default="user@example.com")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()

    try:
        input_path = resolve(args.input)
        out_path = resolve(args.out)
        with input_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        proposal = build_proposal(data, args.owner_email, args.dry_run)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as handle:
            json.dump(proposal, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"wrote: {out_path}")
        print(
            "counts: accounts={accounts} contacts={contacts} interactions={interactions} "
            "owner_owes={owner} others_owe={others}".format(
                accounts=len(proposal["new_account_candidates"]),
                contacts=len(proposal["new_contact_candidates"]),
                interactions=len(proposal["interaction_summaries"]),
                owner=len(proposal["followups_owner_owes"]),
                others=len(proposal["followups_others_owe_owner"]),
            )
        )
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
