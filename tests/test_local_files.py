from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_local_files import collect_local_files  # noqa: E402


class LocalFileTests(unittest.TestCase):
    def test_recent_files_are_scope_bound_without_reading_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "approved-root"
            nested = root / "Project"
            nested.mkdir(parents=True)
            now = datetime(2026, 8, 9, 18, 0, tzinfo=timezone.utc)

            recent = nested / "status.md"
            recent.write_text("sensitive content must not appear in metadata", encoding="utf-8")
            recent_time = (now - timedelta(hours=1)).timestamp()
            os.utime(recent, (recent_time, recent_time))

            old = nested / "old.txt"
            old.write_text("old", encoding="utf-8")
            old_time = (now - timedelta(days=10)).timestamp()
            os.utime(old, (old_time, old_time))

            temporary_office_file = nested / "~$status.docx"
            temporary_office_file.write_text("temporary", encoding="utf-8")

            module = {
                "enabled": True,
                "max_files": 20,
                "roots": [{
                    "path": str(root),
                    "scope_id": "acme",
                    "recursive": True,
                    "lookback_days": 7,
                    "include_extensions": ["md", ".txt", ".docx"],
                }],
            }
            first = collect_local_files(module, now=now)
            second = collect_local_files(module, now=now)

            self.assertEqual(first["gaps"], [])
            self.assertFalse(first["truncated"])
            self.assertEqual(len(first["items"]), 1)
            item = first["items"][0]
            self.assertEqual(item["scope_id"], "acme")
            self.assertEqual(item["kind"], "file")
            self.assertEqual(item["source"]["provider"], "local-files")
            self.assertEqual(item["source"]["relative_path"], str(Path("Project") / "status.md"))
            self.assertNotIn("sensitive content", item["text"])
            self.assertEqual(item["id"], second["items"][0]["id"])

    def test_missing_root_is_reported_as_gap(self) -> None:
        module = {
            "enabled": True,
            "max_files": 20,
            "roots": [{
                "path": str(Path("definitely-missing-close-day-root")),
                "scope_id": "personal",
                "recursive": True,
                "lookback_days": 7,
                "include_extensions": [],
            }],
        }
        result = collect_local_files(module)
        self.assertEqual(result["items"], [])
        self.assertTrue(any("does not exist" in gap for gap in result["gaps"]))

    def test_large_scan_is_bounded_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one.txt").write_text("one", encoding="utf-8")
            (root / "two.txt").write_text("two", encoding="utf-8")
            module = {
                "enabled": True,
                "max_files": 20,
                "max_scanned_files": 1,
                "max_scanned_directories": 100,
                "max_scan_seconds": 30,
                "roots": [{
                    "path": temporary,
                    "scope_id": "personal",
                    "recursive": True,
                    "lookback_days": 7,
                    "include_extensions": [],
                }],
            }
            result = collect_local_files(module)
            self.assertEqual(len(result["items"]), 1)
            self.assertEqual(result["scan_stats"][0]["limited_by"], "files")
            self.assertTrue(any("bounded scan" in gap for gap in result["gaps"]))


if __name__ == "__main__":
    unittest.main()
