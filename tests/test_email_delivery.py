from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_close_email import prepare_email  # noqa: E402
from record_email_delivery import classify_delivery_error, record_delivery  # noqa: E402
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
            self.assertEqual(first["status"], "approval_required")
            self.assertFalse(first["send"])

            approved_state = record_delivery(copy.deepcopy(payload), first, "approved")
            approved = prepare_email(approved_state, value)
            self.assertEqual(approved["status"], "approved_ready")
            self.assertTrue(approved["send"])
            self.assertTrue(approved["approved"])

            pending_state = record_delivery(approved_state, first, "pending")
            pending = prepare_email(pending_state, value)
            self.assertEqual(pending["status"], "pending_review")
            self.assertTrue(pending["requires_sent_check"])
            self.assertFalse(pending["send"])
            resumed_pending = prepare_email(
                pending_state, value, sent_check_absent=True
            )
            self.assertEqual(resumed_pending["status"], "approved_retry")
            self.assertTrue(resumed_pending["send"])
            self.assertFalse(resumed_pending["requires_sent_check"])
            self.assertEqual(pending_state["delivery"]["email"]["attempt_count"], 1)

            state = record_delivery(pending_state, first, "sent")
            repeated = prepare_email(state, value)
            self.assertEqual(repeated["status"], "already_sent")
            self.assertFalse(repeated["send"])

            failed_state = record_delivery(
                record_delivery(copy.deepcopy(payload), first, "approved"),
                first,
                "failed",
                "temporary provider failure",
            )
            retry = prepare_email(failed_state, value)
            self.assertEqual(retry["status"], "sent_check_required")
            self.assertFalse(retry["send"])
            self.assertTrue(retry["requires_sent_check"])
            safe_retry = prepare_email(failed_state, value, sent_check_absent=True)
            self.assertEqual(safe_retry["status"], "approved_retry")
            self.assertTrue(safe_retry["send"])
            self.assertFalse(safe_retry["requires_sent_check"])

            legacy_failed_state = record_delivery(
                copy.deepcopy(payload), first, "failed", "temporary provider failure"
            )
            legacy_failed = prepare_email(legacy_failed_state, value)
            self.assertEqual(legacy_failed["status"], "failed_requires_retry")
            self.assertFalse(legacy_failed["send"])
            legacy_retry = prepare_email(
                legacy_failed_state, value, allow_failed_retry=True
            )
            self.assertEqual(legacy_retry["status"], "sent_check_required")
            self.assertFalse(legacy_retry["send"])
            legacy_retry = prepare_email(
                legacy_failed_state,
                value,
                allow_failed_retry=True,
                sent_check_absent=True,
            )
            self.assertEqual(legacy_retry["status"], "legacy_retry")
            self.assertTrue(legacy_retry["send"])

            changed = copy.deepcopy(payload)
            changed["summary"] = "Changed summary."
            changed_envelope = prepare_email({**changed, "delivery": state["delivery"]}, value)
            self.assertNotEqual(changed_envelope["delivery_key"], first["delivery_key"])
            self.assertEqual(changed_envelope["status"], "approval_required")
            self.assertFalse(changed_envelope["send"])

    def test_failure_classification_and_approval_metadata(self) -> None:
        self.assertEqual(
            classify_delivery_error(
                "Parameters failed connector schema validation: payload required by workspace admin"
            ),
            "workspace_policy",
        )
        self.assertEqual(classify_delivery_error("OAuth scope denied"), "authentication")
        self.assertEqual(classify_delivery_error("temporary timeout"), "transient")

        state = {"date": "2026-08-09"}
        envelope = {
            "delivery_key": "stable-key",
            "from": "sender@example.com",
            "recipients": ["recipient@example.com"],
            "subject": "Daily Success Plan for 2026-08-10",
            "attachment_files": ["Daily Plan 2026-08-10.docx"],
        }
        approved = record_delivery(state, envelope, "approved")
        failed = record_delivery(
            approved,
            envelope,
            "failed",
            "payload required by workspace admin schema",
        )
        record = failed["delivery"]["email"]
        self.assertEqual(record["approved_delivery_key"], "stable-key")
        self.assertTrue(record["approved_at"])
        self.assertEqual(record["error_category"], "workspace_policy")

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
