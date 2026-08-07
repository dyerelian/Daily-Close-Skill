from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from create_close_artifacts import build_outputs, create_task_xlsx, export_paths  # noqa: E402
from propose_crm_from_mail import normalized_email_payload  # noqa: E402


class ArtifactTests(unittest.TestCase):
    def test_normalized_mail_can_feed_crm_proposals(self) -> None:
        payload = normalized_email_payload({
            "items": [
                {
                    "id": "m1",
                    "kind": "message",
                    "title": "Customer follow-up",
                    "text": "Please send the next step",
                    "participants": ["contact@example.org"],
                    "source": {"provider": "outlook", "account": "owner@example.com", "id": "m1"},
                },
                {"id": "manual", "kind": "manual", "text": "Ignore for CRM"},
            ]
        })
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["subject"], "Customer follow-up")

    def test_combined_close_is_scope_labeled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = {
                "artifacts": {
                    "workspace_root": temporary,
                    "path_overrides": {},
                    "canonical": {"markdown": True, "json": True},
                    "exports": {"docx": False, "xlsx": False},
                },
                "scopes": [
                    {"id": "personal", "name": "Personal"},
                    {"id": "acme", "name": "Acme"},
                ],
            }
            payload = {
                "date": "2026-08-07",
                "target_date": "2026-08-10",
                "summary": "One combined close.",
                "takeaways": {"well": [{"text": "Closed the loop", "scope_id": "acme"}], "improve": []},
                "sections": {
                    "accomplished": [{"text": "Finished proposal", "scope_id": "acme"}],
                    "priorities": [{"text": "Exercise", "scope_id": "personal"}],
                    "tasks": [{"text": "Call partner", "scope_id": "acme"}],
                },
                "agendas": [
                    {
                        "title": "Weekly sync",
                        "scope_id": "acme",
                        "last_meeting_recap": {"summary": "Prior decision", "follow_ups": []},
                        "items": ["Next decision"],
                    }
                ],
            }
            outputs = build_outputs(payload, profile)
            rendered = "\n".join(value for value in outputs.values() if isinstance(value, str))
            self.assertIn("[Acme] Finished proposal", rendered)
            self.assertIn("[Personal] Exercise", rendered)
            self.assertIn("Last meeting recap", rendered)
            self.assertEqual(len(outputs), 5)

    def test_optional_export_jobs_are_derived_from_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = {
                "artifacts": {
                    "workspace_root": temporary,
                    "path_overrides": {},
                    "canonical": {"markdown": True, "json": True},
                    "exports": {"docx": True, "xlsx": True},
                },
                "features": {"docx_page_numbers": True},
                "scopes": [{"id": "acme", "name": "Acme"}],
            }
            payload = {
                "date": "2026-08-07",
                "target_date": "2026-08-10",
                "sections": {"tasks": [{"text": "Call partner", "scope_id": "acme"}]},
                "agendas": [{"title": "Weekly sync", "scope_id": "acme"}],
            }
            jobs = export_paths(payload, profile)
            self.assertEqual(len(jobs["docx"]), 2)
            xlsx = jobs["xlsx"]
            create_task_xlsx(payload, profile, xlsx)
            self.assertTrue(xlsx.exists())


if __name__ == "__main__":
    unittest.main()
