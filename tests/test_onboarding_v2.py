from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from close_day_config import load_json, validate_profile  # noqa: E402
from close_day_onboarding import build_profile, validate_setup  # noqa: E402
from install_close_day import environment_report, install  # noqa: E402


class OnboardingTests(unittest.TestCase):
    def test_example_answers_build_valid_profile(self) -> None:
        answers = load_json(ROOT / "config" / "onboarding.answers.example.json")
        profile = build_profile(answers)
        errors, _ = validate_profile(profile)
        self.assertEqual(errors, [])
        readiness = validate_setup(profile)
        self.assertEqual(readiness["status"], "usable_with_gaps")
        self.assertTrue(any("gmail" in item for item in readiness["gaps"]))
        self.assertTrue(any("google" in item for item in readiness["gaps"]))

    def test_installer_dry_run_does_not_create_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "close-day"
            result = install(ROOT, target, "copy", force=False, dry_run=True)
            self.assertEqual(result["status"], "dry_run")
            self.assertFalse(target.exists())
            self.assertTrue(environment_report(target)["python_supported"])

    def test_scoped_jira_and_local_files_are_onboarded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            answers = copy.deepcopy(load_json(ROOT / "config" / "onboarding.answers.example.json"))
            workspace = Path(temporary) / "workspace"
            for folder in ("Plans", "Agendas", "Tasks", "Logs", "State"):
                (workspace / folder).mkdir(parents=True, exist_ok=True)
            answers["artifacts"]["workspace_root"] = str(workspace)
            scope_id = answers["scopes"][0]["id"]
            optional = answers["systems"]["optional_modules"]
            optional["jira-sweep"] = {
                "enabled": True,
                "connector": "atlassian",
                "connector_configured": True,
                "queries": [{
                    "name": "Assigned open work",
                    "jql": "assignee = currentUser() AND statusCategory != Done",
                    "scope_id": scope_id,
                    "limit": 50,
                }],
            }
            optional["local-files"] = {
                "enabled": True,
                "max_files": 200,
                "roots": [{
                    "path": temporary,
                    "scope_id": scope_id,
                    "recursive": True,
                    "lookback_days": 7,
                    "include_extensions": [],
                }],
            }
            profile = build_profile(answers)
            errors, _ = validate_profile(profile, strict_paths=True)
            self.assertEqual(errors, [])
            self.assertIn("jira-sweep", profile["enabled_modules"])
            self.assertIn("local-files", profile["enabled_modules"])
            readiness = validate_setup(profile, strict_paths=True)
            self.assertFalse(any("jira-sweep" in gap for gap in readiness["gaps"]))
            self.assertFalse(any("local-files" in gap for gap in readiness["gaps"]))

    def test_copy_install_excludes_private_legacy_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "close-day"
            result = install(ROOT, target, "copy", force=False, dry_run=False)
            self.assertEqual(result["mode"], "copy")
            self.assertTrue((target / "SKILL.md").exists())
            self.assertFalse((target / "config" / "daily-close.local.json").exists())

    def test_force_install_refuses_to_delete_legacy_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "close-day"
            (target / "config").mkdir(parents=True)
            legacy = target / "config" / "daily-close.local.json"
            legacy.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                install(ROOT, target, "copy", force=True, dry_run=False)
            self.assertTrue(legacy.exists())


if __name__ == "__main__":
    unittest.main()
