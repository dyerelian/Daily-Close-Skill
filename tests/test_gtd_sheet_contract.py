from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gtd_sheet_contract import (  # noqa: E402
    DEFAULT_HEADERS,
    audit_gtd_schema,
    build_gtd_operations,
    build_write_plan,
    validate_gtd_operations,
)


def gtd_profile() -> dict:
    return {
        "scopes": [{"id": "personal"}, {"id": "org"}],
        "permissions": {"gtd_writes_enabled": True},
        "modules": {
            "gtd-google-sheet": {
                "enabled": True,
                "allow_writes": True,
                "scope_ids": ["personal", "org"],
                "area_values": {"personal": "Pers", "org": "Org"},
                "context_values": ["@Computer", "@Calls", "@Errands", "@Anywhere"],
                "tab_map": {
                    "next_actions": "Next Actions",
                    "waiting_fors": "Waiting Fors",
                    "inbox": "Inbox",
                    "archive": "Action Archive",
                },
                "archive_before_clear": True,
            }
        },
    }


class GtdSheetContractTests(unittest.TestCase):
    def test_schema_audit_accepts_exact_required_headers(self) -> None:
        profile = gtd_profile()
        headers = {
            profile["modules"]["gtd-google-sheet"]["tab_map"][key]: value
            for key, value in DEFAULT_HEADERS.items()
        }
        self.assertTrue(audit_gtd_schema(headers, profile["modules"]["gtd-google-sheet"])["valid"])
        headers["Next Actions"] = ["Wrong"]
        self.assertFalse(audit_gtd_schema(headers, profile["modules"]["gtd-google-sheet"])["valid"])

    def test_action_proposal_builds_next_action_and_waiting_rows(self) -> None:
        proposal = {
            "items": [
                {
                    "scope_id": "personal", "title": "Book appointment", "action_kind": "next_action",
                    "primary_destination": "gtd", "close_action_id": "a1", "external_key": "close-day:a1",
                },
                {
                    "scope_id": "org", "title": "Await approval", "action_kind": "waiting_for",
                    "primary_destination": "gtd", "close_action_id": "a2", "external_key": "close-day:a2",
                    "owner": "Legal",
                },
            ]
        }
        operations = build_gtd_operations(proposal, gtd_profile())
        self.assertEqual([operation["tab"] for operation in operations], ["Next Actions", "Waiting Fors"])
        self.assertEqual(operations[0]["row"]["Context"], "@Anywhere")
        self.assertEqual(validate_gtd_operations(operations, gtd_profile()), [])

    def test_soft_dates_become_review_dates_and_hard_dates_remain_due(self) -> None:
        proposal = {
            "items": [
                {
                    "scope_id": "personal", "title": "Review options", "action_kind": "next_action",
                    "primary_destination": "gtd", "close_action_id": "soft", "due": "2026-09-08",
                },
                {
                    "scope_id": "org", "title": "File response", "action_kind": "next_action",
                    "primary_destination": "gtd", "close_action_id": "hard", "due": "2026-11-17",
                    "due_is_hard": True, "context": "@Computer",
                },
            ]
        }
        operations = build_gtd_operations(proposal, gtd_profile())
        soft, hard = (operation["row"] for operation in operations)
        self.assertEqual(soft["Defer / Review On"], "2026-09-08")
        self.assertIsNone(soft["Due"])
        self.assertIsNone(hard["Defer / Review On"])
        self.assertEqual(hard["Due"], "2026-11-17")

    def test_existing_action_is_updated_instead_of_appended(self) -> None:
        profile = gtd_profile()
        operation = {
            "operation": "upsert", "tab": "Next Actions", "scope_id": "personal",
            "close_action_id": "a1", "row": {"Next Action": "Call"},
        }
        plan = build_write_plan([operation], profile, {"a1": {"tab": "Next Actions", "row_number": 7}})
        self.assertEqual(plan[0]["action"], "update")
        self.assertEqual(plan[0]["row_number"], 7)

    def test_archive_is_ordered_before_clear(self) -> None:
        profile = gtd_profile()
        operation = {
            "operation": "archive_and_clear",
            "origin_tab": "Next Actions",
            "row_number": 4,
            "scope_id": "personal",
            "close_action_id": "a1",
            "archive_record": {"Item": "Done item", "Final Status": "Done"},
        }
        self.assertEqual(validate_gtd_operations([operation], profile), [])
        plan = build_write_plan([operation], profile)
        self.assertEqual([step["action"] for step in plan], ["append", "clear"])
        self.assertEqual(plan[1]["depends_on"], "archive:a1")

    def test_write_permission_is_independent(self) -> None:
        profile = gtd_profile()
        profile["permissions"]["gtd_writes_enabled"] = False
        errors = validate_gtd_operations([{
            "operation": "upsert", "tab": "Next Actions", "scope_id": "personal",
            "close_action_id": "a1", "row": {"Context": "@Anywhere"},
        }], profile)
        self.assertTrue(any("gtd_writes_enabled" in error for error in errors))

    def test_exact_action_approval_can_be_enforced(self) -> None:
        operation = {
            "operation": "upsert", "tab": "Next Actions", "scope_id": "personal",
            "close_action_id": "a1", "row": {"Context": "@Anywhere"},
        }
        errors = validate_gtd_operations([operation], gtd_profile(), [])
        self.assertTrue(any("exact action approval" in error for error in errors))
        self.assertEqual(validate_gtd_operations([operation], gtd_profile(), ["a1"]), [])


if __name__ == "__main__":
    unittest.main()
