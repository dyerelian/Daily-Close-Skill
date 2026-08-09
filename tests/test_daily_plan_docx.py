from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "create_daily_plan_docx.py"


class FakeAgenda:
    @staticmethod
    def text(value):
        return "" if value is None else str(value)

    @staticmethod
    def run_xml(value, **_kwargs):
        return f"<w:r><w:t>{value}</w:t></w:r>"

    @staticmethod
    def paragraph_xml(runs, **_kwargs):
        return f"<w:p>{''.join(runs)}</w:p>"

    @staticmethod
    def simple_paragraph(value, **_kwargs):
        return f"<w:p><w:r><w:t>{value}</w:t></w:r></w:p>"

    @staticmethod
    def document_body(_agenda):
        return "<w:p><w:r><w:t>Agenda body</w:t></w:r></w:p>"

    @staticmethod
    def content_types_xml():
        return '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>'

    @staticmethod
    def root_rels_xml():
        return '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'

    @staticmethod
    def document_rels_xml():
        return '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'

    @staticmethod
    def styles_xml():
        return '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'


def load_module():
    spec = importlib.util.spec_from_file_location("daily_plan_renderer", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    module.ac = FakeAgenda()
    return module


class DailyPlanDocxTests(unittest.TestCase):
    def test_bundled_renderer_creates_plan_without_embedded_agendas(self) -> None:
        spec = importlib.util.spec_from_file_location("daily_plan_bundled", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        self.assertEqual(module.AGENDA_SCRIPT, ROOT / "scripts" / "create_agenda_docx.py")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundled.docx"
            module.create_docx(
                {
                    "date": "2026-08-08",
                    "takeaways": {"well": ["Useful close"], "improve": []},
                    "agendas": [{"title": "Weekly sync", "items": ["Decision"]}],
                },
                output,
            )
            with zipfile.ZipFile(output) as archive:
                self.assertIn("word/footer1.xml", archive.namelist())
                document = archive.read("word/document.xml").decode("utf-8")
                self.assertIn("Yesterday — 1 thing I did well", document)
                self.assertNotIn("Weekly sync", document)

    def test_takeaways_and_page_footer_are_packaged(self) -> None:
        module = load_module()
        data = {
            "title": "Daily Plan",
            "date": "2026-08-08",
            "summary": "Summary",
            "takeaways": {"source_day": "2026-08-07", "well": ["Good"], "improve": ["Better"]},
            "page_numbers": True,
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "plan.docx"
            module.create_docx(data, output)
            with zipfile.ZipFile(output) as archive:
                self.assertIn("word/footer1.xml", archive.namelist())
                document = archive.read("word/document.xml").decode("utf-8")
                self.assertIn("Yesterday — 1 thing I did well", document)
                self.assertIn("Today — 1 thing I can improve", document)
                self.assertLess(document.index("Yesterday"), document.index("Summary"))
                self.assertIn("footerReference", document)
                footer = archive.read("word/footer1.xml").decode("utf-8")
                self.assertIn("NUMPAGES", footer)
                numbering = archive.read("word/numbering.xml").decode("utf-8")
                self.assertIn('w:numFmt w:val="decimal"', numbering)
                styles = archive.read("word/styles.xml").decode("utf-8")
                self.assertIn('w:line="300"', styles)
                self.assertIn('w:color w:val="2E74B5"', styles)

    def test_page_numbers_can_be_disabled(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "plan.docx"
            module.create_docx({"title": "Plan", "page_numbers": False}, output)
            with zipfile.ZipFile(output) as archive:
                self.assertNotIn("word/footer1.xml", archive.namelist())


if __name__ == "__main__":
    unittest.main()
