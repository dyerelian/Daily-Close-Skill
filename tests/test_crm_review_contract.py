from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from crm_review_contract import build_review_state, normalize_proposal, prepare_request  # noqa: E402
from test_close_day_config import profile as base_profile  # noqa: E402


class CrmReviewContractTests(unittest.TestCase):
    def configured_profile(self, workspace: Path) -> dict:
        value = base_profile(workspace)
        value["owner"]["timezone"] = "America/Los_Angeles"
        value["permissions"]["crm_writes_enabled"] = True
        value["enabled_modules"].append("crm-google-sheet")
        value["modules"]["crm-google-sheet"] = {
            "enabled": True,
            "mode": "delegated_handler",
            "scope_ids": ["acme"],
            "handler_skill": "update-crm",
            "review_mode": "incremental_daily",
            "first_run_lookback_days": 14,
            "overlap_hours": 24,
            "allow_new_rows": True,
            "minimum_confidence": "medium",
            "allow_live_sheet_writes": True,
            "roll_weekly_jira": False,
        }
        return value

    def test_first_request_is_scoped_deduplicated_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            value = self.configured_profile(workspace)
            meeting = {
                "id": "meeting-1",
                "kind": "meeting",
                "title": "Partner sync",
                "timestamp": "2026-08-13T07:00:00-07:00",
                "source": {"provider": "google", "id": "meeting-1"},
            }
            routed = {
                "classified": [
                    {"status": "classified", "scope_id": "acme", "item": meeting},
                    {"status": "classified", "scope_id": "acme", "item": copy.deepcopy(meeting)},
                    {
                        "status": "classified",
                        "scope_id": "acme",
                        "item": {
                            "id": "old",
                            "timestamp": "2026-01-01T09:00:00-08:00",
                            "source": {"provider": "google", "id": "old"},
                        },
                    },
                    {
                        "status": "classified",
                        "scope_id": "personal",
                        "item": {"id": "personal", "source": {"provider": "manual"}},
                    },
                ],
                "excluded": [{"status": "excluded", "item": {"id": "hidden"}}],
            }
            close_at = datetime(2026, 8, 14, 17, tzinfo=timezone(timedelta(hours=-7)))
            first = prepare_request(value, routed, close_at, workspace / "State")
            second = prepare_request(value, routed, close_at, workspace / "State")
            self.assertEqual(first["request_id"], second["request_id"])
            self.assertTrue(first["window"]["first_run"])
            self.assertEqual(first["window"]["start"], "2026-07-31T17:00:00-07:00")
            self.assertEqual(len(first["evidence"]), 1)
            self.assertEqual(first["evidence"][0]["scope_id"], "acme")
            self.assertFalse(first["policy"]["roll_weekly_jira"])

    def test_completed_state_sets_overlap_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state_dir = workspace / "State"
            state_dir.mkdir()
            value = self.configured_profile(workspace)
            (state_dir / "2026-08-13-close.json").write_text(
                json.dumps(
                    {
                        "crm_review": {
                            "status": "completed",
                            "profile_id": "portfolio",
                            "scope_ids": ["acme"],
                            "reviewed_through": "2026-08-13T17:00:00-07:00",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (state_dir / "2026-08-15-close.json").write_text(
                json.dumps(
                    {
                        "crm_review": {
                            "status": "completed",
                            "profile_id": "portfolio",
                            "scope_ids": ["acme"],
                            "reviewed_through": "2026-08-15T17:00:00-07:00",
                        }
                    }
                ),
                encoding="utf-8",
            )
            close_at = datetime(2026, 8, 14, 17, tzinfo=timezone(timedelta(hours=-7)))
            request = prepare_request(value, [], close_at, state_dir)
            self.assertFalse(request["window"]["first_run"])
            self.assertEqual(request["window"]["start"], "2026-08-12T17:00:00-07:00")

    def test_proposal_assigns_ids_and_rejects_low_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value = self.configured_profile(Path(temporary))
            request = prepare_request(
                value,
                [],
                datetime(2026, 8, 14, 17, tzinfo=timezone(timedelta(hours=-7))),
                Path(temporary) / "State",
            )
            change = {
                "scope_id": "acme",
                "operation": "update_cells",
                "row": {"company": "Acme", "email": "lead@acme.example"},
                "cells": [{"column": "Last Interaction", "old": "", "new": "2026-08-13"}],
                "confidence": "medium",
                "inferred": True,
                "evidence_refs": ["google:meeting-1"],
                "rationale": "Completed external meeting.",
            }
            proposal = {
                "contract_version": 1,
                "request_id": request["request_id"],
                "source_coverage": [{"source": "calendar", "status": "available"}],
                "gaps": [],
                "review_flags": [],
                "derived_follow_ups": [],
                "changes": [change],
            }
            normalized, errors = normalize_proposal(request, proposal)
            self.assertEqual(errors, [])
            self.assertEqual(len(normalized["changes"][0]["change_id"]), 64)
            repeated, errors = normalize_proposal(request, normalized)
            self.assertEqual(errors, [])
            self.assertEqual(
                normalized["changes"][0]["change_id"], repeated["changes"][0]["change_id"]
            )

            proposal["changes"][0]["confidence"] = "low"
            _, errors = normalize_proposal(request, proposal)
            self.assertTrue(any("threshold" in error for error in errors))

    def test_completed_state_requires_decisions_and_verified_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value = self.configured_profile(Path(temporary))
            request = prepare_request(
                value,
                [],
                datetime(2026, 8, 14, 17, tzinfo=timezone(timedelta(hours=-7))),
                Path(temporary) / "State",
            )
            proposal = {
                "contract_version": 1,
                "request_id": request["request_id"],
                "source_coverage": [{"source": "calendar", "status": "available"}],
                "gaps": [],
                "review_flags": [],
                "derived_follow_ups": [],
                "changes": [{
                    "scope_id": "acme",
                    "operation": "update_cells",
                    "row": {"company": "Acme"},
                    "cells": [{"column": "Last Interaction", "old": "", "new": "2026-08-13"}],
                    "confidence": "high",
                    "inferred": False,
                    "evidence_refs": ["gmail:m1"],
                    "rationale": "Confirmed follow-up email.",
                }],
            }
            normalized, errors = normalize_proposal(request, proposal)
            self.assertEqual(errors, [])
            change_id = normalized["changes"][0]["change_id"]
            state, errors = build_review_state(
                request,
                normalized,
                {
                    "status": "completed",
                    "approved_change_ids": [change_id],
                    "applied_change_ids": [change_id],
                    "rejected_change_ids": [],
                    "summary_items": [{"text": "Updated Acme", "scope_id": "acme"}],
                },
            )
            self.assertEqual(errors, [])
            self.assertEqual(state["reviewed_through"], request["window"]["end"])
            self.assertEqual(state["counts"]["applied"], 1)

            _, errors = build_review_state(
                request,
                normalized,
                {
                    "status": "completed",
                    "approved_change_ids": [change_id],
                    "applied_change_ids": [],
                    "rejected_change_ids": [],
                },
            )
            self.assertTrue(any("every approved change" in error for error in errors))

            _, errors = build_review_state(
                request,
                normalized,
                {
                    "status": "failed",
                    "approved_change_ids": [],
                    "applied_change_ids": [],
                    "rejected_change_ids": [],
                    "gaps": "CRM unavailable",
                    "summary_items": "not an array",
                },
            )
            self.assertTrue(any("outcome gaps" in error for error in errors))
            self.assertTrue(any("outcome summary_items" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
