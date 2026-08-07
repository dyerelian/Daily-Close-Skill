from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from close_day_config import (  # noqa: E402
    classify_items,
    load_registry,
    migrate_v1_profile,
    register_profile,
    resolve_profile,
    validate_profile,
)


def profile(workspace: Path) -> dict:
    return {
        "schema_version": 2,
        "profile": {"id": "portfolio", "name": "Portfolio"},
        "owner": {"name": "User", "primary_email": "user@example.com", "timezone": "UTC"},
        "schedule": {"workdays": ["Monday"], "close_out_time": "17:00"},
        "scopes": [
            {
                "id": "personal",
                "type": "personal",
                "name": "Personal",
                "aliases": ["Personal"],
                "domains": [],
                "include_terms": ["home"],
                "exclude_terms": [],
                "source_bindings": ["personal@example.com"],
            },
            {
                "id": "acme",
                "type": "organization",
                "name": "Acme",
                "aliases": ["Acme"],
                "domains": ["acme.example"],
                "include_terms": ["Roadrunner"],
                "exclude_terms": [],
                "source_bindings": ["work@example.com"],
            },
        ],
        "routing": {
            "unclassified_policy": "pause_and_ask",
            "global_exclusions": [{"name": "Hidden", "match_terms": ["INTERNAL-ONLY"]}],
        },
        "artifacts": {
            "workspace_root": str(workspace),
            "path_overrides": {},
            "canonical": {"markdown": True, "json": True},
            "exports": {"docx": False, "xlsx": False},
        },
        "features": {},
        "permissions": {
            "proposal_required": True,
            "external_writes_enabled": False,
            "local_artifact_writes_enabled": False,
            "jira_ticket_approval_required": True,
            "crm_writes_enabled": False,
        },
        "enabled_modules": ["task-store", "daily-artifacts"],
        "modules": {
            "task-store": {"enabled": True, "provider": "portable", "existing_path": None, "allow_writes": False},
            "daily-artifacts": {"enabled": True},
            "mail-sweep": {
                "enabled": False,
                "providers": [{"provider": "gmail", "account": "only@acme.example", "scope_ids": ["acme"]}],
            },
        },
    }


class ProfileTests(unittest.TestCase):
    def test_validation_and_registry_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = profile(root / "workspace")
            errors, warnings = validate_profile(value)
            self.assertEqual(errors, [])
            self.assertTrue(warnings)
            destination = register_profile(value, root / "config", make_default=True)
            self.assertTrue(destination.exists())
            registry = load_registry(root / "config")
            self.assertEqual(registry["default_profile_id"], "portfolio")
            loaded, loaded_path = resolve_profile(None, root / "config")
            self.assertEqual(loaded["profile"]["id"], "portfolio")
            self.assertEqual(loaded_path, destination)

    def test_routing_precedence_exclusion_and_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value = profile(Path(temporary))
            result = classify_items(
                [
                    {"id": "1", "title": "Unrelated", "source": {"account": "work@example.com"}},
                    {"id": "2", "title": "Meeting", "participants": ["lead@acme.example"]},
                    {"id": "3", "text": "Roadrunner decision"},
                    {"id": "4", "text": "INTERNAL-ONLY project item"},
                    {"id": "5", "text": "Unknown item"},
                    {"id": "6", "text": "Provider-bound", "source": {"provider": "gmail", "account": "only@acme.example"}},
                ],
                value,
            )
            self.assertEqual([item["scope_id"] for item in result["classified"]], ["acme", "acme", "acme", "acme"])
            self.assertEqual(len(result["excluded"]), 1)
            self.assertEqual(len(result["unclassified"]), 1)
            self.assertTrue(result["requires_resolution"])

    def test_v1_migration_preserves_exclusions_and_permissions(self) -> None:
        legacy = {
            "profile_name": "old-profile",
            "owner": {"name": "User", "primary_email": "u@example.com", "timezone": "UTC"},
            "scope_exclusions": {
                "topics": [{"name": "Excluded Account", "match_terms": ["EXCLUDED"], "reason": "ignored"}]
            },
            "write_mode": {"external_writes_enabled": True, "document_generation_enabled": False},
            "enabled_modules": ["gmail-sweep", "calendar-outlook", "crm-google-sheet"],
            "paths": {},
            "crm": {"workbook_path": "legacy-crm.xlsx", "csv_seed_dir": "legacy-csv"},
            "modules": {
                "gmail-sweep": {"account": "u@example.com"},
                "crm-google-sheet": {"workbook_path": "legacy-crm.xlsx", "proposal_output_dir": "legacy-proposals"},
            },
        }
        migrated = migrate_v1_profile(legacy)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["routing"]["global_exclusions"][0]["name"], "Excluded Account")
        self.assertTrue(migrated["permissions"]["external_writes_enabled"])
        self.assertEqual(migrated["modules"]["crm-google-sheet"]["csv_seed_dir"], "legacy-csv")
        errors, _ = validate_profile(migrated)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
