from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from people_outreach import commit_selection, select_people  # noqa: E402


class PeopleOutreachTests(unittest.TestCase):
    def profile(self, root: Path) -> dict:
        list_path = root / "people.json"
        list_path.write_text(json.dumps({"schema_version": 1, "people": ["A", "B", "Elle", "Elle"]}), encoding="utf-8")
        return {
            "features": {
                "people_outreach": {
                    "enabled": True,
                    "daily_count": 2,
                    "list_path": str(list_path),
                    "state_path": str(root / "state.json"),
                    "selection_policy": "round_robin",
                    "duplicate_policy": "count_entries",
                }
            }
        }

    def test_round_robin_counts_duplicate_entries_and_reuses_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self.profile(root)
            first = select_people(profile, "2026-08-27", {})
            self.assertEqual(first["people"], ["A", "B"])
            commit_selection(profile, first, approved=True)
            state = json.loads((root / "state.json").read_text(encoding="utf-8"))
            second = select_people(profile, "2026-08-28", state)
            self.assertEqual(second["people"], ["Elle", "Elle"])
            repeat = select_people(profile, "2026-08-27", state)
            self.assertEqual(repeat["people"], ["A", "B"])

    def test_unapproved_commit_does_not_write_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self.profile(root)
            with self.assertRaises(PermissionError):
                commit_selection(profile, select_people(profile, "2026-08-27", {}))
            self.assertFalse((root / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
