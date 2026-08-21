from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from action_routing_contract import (  # noqa: E402
    build_execution_plan,
    prepare_action_proposal,
    stable_action_id,
    validate_action_proposal,
)


def routing_profile() -> dict:
    return {
        "scopes": [{"id": "personal"}, {"id": "org"}],
        "permissions": {
            "gtd_writes_enabled": True,
            "jira_writes_enabled": True,
            "crm_writes_enabled": True,
        },
        "modules": {
            "action-routing": {
                "enabled": True,
                "overlap_policy": "primary_with_links",
                "unready_policy": "pause_and_ask",
                "destinations": {
                    "gtd": "gtd-google-sheet",
                    "jira": "jira-sweep",
                    "crm": "crm-google-sheet",
                },
            },
            "gtd-google-sheet": {"enabled": True},
            "jira-sweep": {"enabled": True},
            "crm-google-sheet": {"enabled": True},
        },
    }


class ActionRoutingContractTests(unittest.TestCase):
    def test_stable_ids_dedupe_retries(self) -> None:
        item = {
            "scope_id": "personal",
            "title": "Call the dentist",
            "source": {"provider": "gmail", "id": "thread-1"},
        }
        self.assertEqual(stable_action_id(item), stable_action_id(dict(item)))
        proposal = prepare_action_proposal([item, dict(item)], routing_profile())
        self.assertEqual(len(proposal["items"]), 1)

    def test_team_work_routes_to_jira_with_linked_crm_record(self) -> None:
        proposal = prepare_action_proposal(
            [{
                "scope_id": "org",
                "title": "Ship the onboarding flow",
                "action_kind": "team_project_work",
                "acceptance_criteria": ["Owner can complete setup"],
                "crm_applicable": True,
            }],
            routing_profile(),
        )
        item = proposal["items"][0]
        self.assertEqual(item["primary_destination"], "jira")
        self.assertEqual(item["secondary_records"][0]["destination"], "crm")
        plan = build_execution_plan(proposal)
        self.assertEqual(plan[1]["depends_on"], plan[0]["operation_key"])

    def test_personal_and_waiting_work_route_to_gtd(self) -> None:
        proposal = prepare_action_proposal(
            [
                {"scope_id": "personal", "title": "Book appointment", "action_kind": "next_action"},
                {"scope_id": "org", "title": "Await legal review", "action_kind": "waiting_for"},
            ],
            routing_profile(),
        )
        self.assertEqual([item["primary_destination"] for item in proposal["items"]], ["gtd", "gtd"])

    def test_profile_rules_can_change_the_primary_destination(self) -> None:
        profile = routing_profile()
        profile["modules"]["action-routing"]["rules"] = {"team_project_work": "gtd"}
        proposal = prepare_action_proposal(
            [{"scope_id": "org", "title": "Small team action", "action_kind": "team_project_work"}],
            profile,
        )
        self.assertEqual(proposal["items"][0]["primary_destination"], "gtd")

    def test_crm_only_executable_work_is_rejected(self) -> None:
        proposal = prepare_action_proposal(
            [{
                "scope_id": "org",
                "title": "Follow up with customer",
                "action_kind": "follow_up",
                "primary_destination": "crm",
            }],
            routing_profile(),
        )
        self.assertTrue(proposal["requires_resolution"])
        self.assertEqual(len(proposal["rejected"]), 1)

    def test_exact_approval_and_narrow_permissions_are_required(self) -> None:
        profile = routing_profile()
        proposal = prepare_action_proposal(
            [{"scope_id": "org", "title": "Create rollout ticket", "action_kind": "team_project_work"}],
            profile,
        )
        action_id = proposal["items"][0]["close_action_id"]
        self.assertEqual(validate_action_proposal(proposal, profile, [action_id]), [])
        profile["permissions"]["jira_writes_enabled"] = False
        errors = validate_action_proposal(proposal, profile, [action_id])
        self.assertTrue(any("jira_writes_enabled" in error for error in errors))
        profile["permissions"]["jira_writes_enabled"] = True
        errors = validate_action_proposal(proposal, profile)
        self.assertTrue(any("approved action ids" in error for error in errors))
        errors = validate_action_proposal(proposal, profile, ["another-id"])
        self.assertTrue(any("exact action approval" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
