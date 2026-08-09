from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_close_email import prepare_email  # noqa: E402
from record_email_delivery import record_delivery  # noqa: E402
from test_close_day_config import profile as base_profile  # noqa: E402


class EmailDeliveryTests(unittest.TestCase):
    def configured_profile(self, workspace: Path) -> dict:
        value = base_profile(workspace)
        value["artifacts"]["exports"]["daily_plan_docx"] = True
        value["permissions"]["email_delivery_enabled"] = True
        value["enabled_modules"].append("email-delivery")
        value["modules"]["email-delivery"] = {
            "enabled": True,
            "provider": "gmail",
            "connector": "gmail",
            "connector_configured": True,
            "from": "sender@example.com",
            "recipients": ["recipient@example.com"],
            "mode": "send_after_approved_close",
            "subject_template": "Daily Success Plan for {target_date}",
            "body_style": "summary",
            "attachments": ["daily_plan_docx"],
        }
        return value

    def test_envelope_and_delivery_key_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            plans = workspace / "Plans"
            plans.mkdir()
            (plans / "Daily Plan 2026-08-10.docx").write_bytes(b"docx")
            value = self.configured_profile(workspace)
            payload = {
                "date": "2026-08-09",
                "target_date": "2026-08-10",
                "summary": "Focused day.",
                "sections": {"priorities": ["First", "Second"]},
            }
            first = prepare_email(payload, value)
            second = prepare_email(copy.deepcopy(payload), value)
            self.assertEqual(first["delivery_key"], second["delivery_key"])
            self.assertEqual(first["subject"], "Daily Success Plan for 2026-08-10")
            self.assertEqual(first["to"], "recipient@example.com")
            self.assertEqual(len(first["attachment_files"]), 1)
            state = record_delivery(copy.deepcopy(payload), first, "sent")
            repeated = prepare_email(state, value)
            self.assertEqual(repeated["status"], "already_sent")
            self.assertFalse(repeated["send"])

            failed_state = record_delivery(copy.deepcopy(payload), first, "failed", "temporary")
            failed = prepare_email(failed_state, value)
            self.assertEqual(failed["status"], "failed_requires_retry")
            self.assertFalse(failed["send"])
            retry = prepare_email(failed_state, value, allow_failed_retry=True)
            self.assertEqual(retry["status"], "ready")
            self.assertTrue(retry["send"])

            pending_state = record_delivery(copy.deepcopy(payload), first, "pending")
            pending = prepare_email(pending_state, value)
            self.assertEqual(pending["status"], "pending_review")
            self.assertFalse(pending["send"])

    def test_missing_attachment_and_connector_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value = self.configured_profile(Path(temporary))
            payload = {"date": "2026-08-09", "target_date": "2026-08-10"}
            with self.assertRaises(FileNotFoundError):
                prepare_email(payload, value)
            value["modules"]["email-delivery"]["connector_configured"] = False
            with self.assertRaises(RuntimeError):
                prepare_email(payload, value)


if __name__ == "__main__":
    unittest.main()
