from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from create_close_artifacts import (  # noqa: E402
    build_outputs,
    create_task_xlsx,
    eod_markdown,
    export_paths,
    plan_markdown,
    prepare_people_outreach_selection,
    validate_planning_policy,
    validate_required_takeaways,
)
from close_payload import normalize_payload  # noqa: E402
from people_outreach import commit_selection, select_people  # noqa: E402
from propose_crm_from_mail import normalized_email_payload  # noqa: E402


class ArtifactTests(unittest.TestCase):
    def test_planning_fixture_satisfies_configured_windows(self) -> None:
        payload = json.loads(
            (ROOT / "tests" / "fixtures" / "planning_payload_sample.json").read_text(
                encoding="utf-8"
            )
        )
        profile = {
            "owner": {"timezone": "America/Los_Angeles"},
            "schedule": {
                "planning_policy": {
                    "focused_work_windows": {
                        "mylanguage": [
                            {"start": "06:00", "end": "09:00"},
                            {"start": "21:00", "end": "23:00"},
                        ]
                    },
                    "daytime_window": {
                        "start": "09:00",
                        "end": "21:00",
                        "max_total_minutes": 60,
                    },
                    "daytime_rules": [
                        {
                            "scope_id": "mylanguage",
                            "work_type": "check_in",
                            "max_item_minutes": 15,
                        },
                        {
                            "scope_id": "personal",
                            "work_type": "personal",
                            "max_item_minutes": 30,
                        },
                    ],
                    "calendar_commitments": "show_as_fixed_exceptions",
                }
            },
        }
        validate_planning_policy(payload, profile)

    def test_planning_policy_enforces_windows_limits_and_calendar_exceptions(self) -> None:
        profile = {
            "owner": {"timezone": "America/Los_Angeles"},
            "schedule": {
                "planning_policy": {
                    "focused_work_windows": {
                        "acme": [
                            {"start": "06:00", "end": "09:00"},
                            {"start": "21:00", "end": "23:00"},
                        ]
                    },
                    "daytime_window": {
                        "start": "09:00",
                        "end": "21:00",
                        "max_total_minutes": 60,
                    },
                    "daytime_rules": [
                        {"scope_id": "acme", "work_type": "check_in", "max_item_minutes": 15},
                        {"scope_id": "personal", "work_type": "personal", "max_item_minutes": 30},
                    ],
                    "calendar_commitments": "show_as_fixed_exceptions",
                }
            },
        }
        payload = {
            "target_date": "2026-09-18",
            "sections": {
                "tasks": [
                    {
                        "text": "Draft customer response",
                        "scope_id": "acme",
                        "work_type": "focused_work",
                        "start": "2026-09-18T06:30:00-07:00",
                        "end": "2026-09-18T08:00:00-07:00",
                    },
                    {
                        "text": "Check replies",
                        "scope_id": "acme",
                        "work_type": "check_in",
                        "start": "2026-09-18T12:00:00-07:00",
                        "end": "2026-09-18T12:15:00-07:00",
                    },
                    {
                        "text": "Personal administration",
                        "scope_id": "personal",
                        "work_type": "personal",
                        "start": "2026-09-18T17:30:00-07:00",
                        "end": "2026-09-18T18:00:00-07:00",
                    },
                ],
                "meetings": [
                    {
                        "title": "Booked customer meeting",
                        "scope_id": "acme",
                        "start": "2026-09-18T10:00:00-07:00",
                        "end": "2026-09-18T11:00:00-07:00",
                    }
                ],
            },
        }
        validate_planning_policy(payload, profile)

        invalid = payload.copy()
        invalid["sections"] = {**payload["sections"], "tasks": [dict(payload["sections"]["tasks"][0])]}
        invalid["sections"]["tasks"][0].update(
            {
                "start": "2026-09-18T13:00:00-07:00",
                "end": "2026-09-18T14:00:00-07:00",
            }
        )
        with self.assertRaisesRegex(ValueError, "not allowed"):
            validate_planning_policy(invalid, profile)

    def test_planning_policy_rejects_daytime_overage_and_meeting_overlap(self) -> None:
        profile = {
            "owner": {"timezone": "America/Los_Angeles"},
            "schedule": {
                "planning_policy": {
                    "focused_work_windows": {"acme": [{"start": "06:00", "end": "09:00"}]},
                    "daytime_window": {"start": "09:00", "end": "21:00", "max_total_minutes": 30},
                    "daytime_rules": [
                        {"scope_id": "personal", "work_type": "personal", "max_item_minutes": 30}
                    ],
                    "calendar_commitments": "show_as_fixed_exceptions",
                }
            },
        }
        payload = {
            "target_date": "2026-09-18",
            "sections": {
                "tasks": [
                    {
                        "text": "First personal task",
                        "scope_id": "personal",
                        "work_type": "personal",
                        "start": "2026-09-18T12:00:00-07:00",
                        "end": "2026-09-18T12:20:00-07:00",
                    },
                    {
                        "text": "Second personal task",
                        "scope_id": "personal",
                        "work_type": "personal",
                        "start": "2026-09-18T13:00:00-07:00",
                        "end": "2026-09-18T13:20:00-07:00",
                    },
                ]
            },
        }
        with self.assertRaisesRegex(ValueError, "totals 40 minutes"):
            validate_planning_policy(payload, profile)

        payload["sections"]["tasks"] = [payload["sections"]["tasks"][0]]
        payload["sections"]["meetings"] = [
            {
                "title": "Personal appointment",
                "scope_id": "personal",
                "start": "2026-09-18T12:10:00-07:00",
                "end": "2026-09-18T12:30:00-07:00",
            }
        ]
        with self.assertRaisesRegex(ValueError, "overlaps calendar commitment"):
            validate_planning_policy(payload, profile)

    def test_legacy_top_level_sections_are_normalized(self) -> None:
        payload = {
            "date": "2026-08-07",
            "target_date": "2026-08-10",
            "priorities": [{"text": "Restore priority rendering", "scope_id": "acme"}],
            "tasks": [{"text": "Verify the emailed plan", "scope_id": "acme"}],
        }
        normalized = normalize_payload(payload)
        self.assertEqual(normalized["sections"]["priorities"], payload["priorities"])
        self.assertEqual(normalized["sections"]["tasks"], payload["tasks"])
        with tempfile.TemporaryDirectory() as temporary:
            profile = {
                "artifacts": {
                    "workspace_root": temporary,
                    "path_overrides": {},
                    "canonical": {"markdown": True, "json": True},
                    "exports": {"docx": False, "xlsx": False},
                },
                "scopes": [{"id": "acme", "name": "Acme"}],
            }
            rendered = "\n".join(value for value in build_outputs(payload, profile).values() if isinstance(value, str))
            self.assertIn("[Acme] Restore priority rendering", rendered)
            self.assertIn("[Acme] Verify the emailed plan", rendered)

    def test_conflicting_section_representations_fail(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicting"):
            normalize_payload({
                "priorities": ["top-level"],
                "sections": {"priorities": ["nested"]},
            })

    def test_people_outreach_flows_into_daily_plan_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = {
                "artifacts": {
                    "workspace_root": temporary,
                    "path_overrides": {},
                    "canonical": {"markdown": True, "json": True},
                    "exports": {"daily_plan_docx": True},
                },
                "features": {"docx_page_numbers": True},
                "scopes": [],
            }
            payload = {
                "date": "2026-08-27",
                "target_date": "2026-08-28",
                "sections": {"priorities": ["Priority"], "people_outreach": ["Reach out to A", "Reach out to B"]},
            }
            jobs = export_paths(payload, profile)
            self.assertEqual(jobs["docx"][0][1]["people_outreach"], ["Reach out to A", "Reach out to B"])
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

    def test_eod_log_records_compact_crm_review(self) -> None:
        payload = {
            "date": "2026-08-14",
            "crm_review": {
                "status": "completed",
                "handler_skill": "update-crm",
                "window": {
                    "start": "2026-08-13T17:00:00-07:00",
                    "end": "2026-08-14T17:00:00-07:00",
                },
                "counts": {"applied": 2, "rejected": 1},
                "summary_items": [
                    {"text": "Updated Acme last interaction", "scope_id": "acme"}
                ],
                "review_flags": [
                    {"text": "Confirm partner role", "scope_id": "acme"}
                ],
                "gaps": ["Slack unavailable"],
            },
        }
        rendered = eod_markdown(payload, {"acme": "Acme"})
        self.assertIn("CRM Review", rendered)
        self.assertIn("[Acme] Updated Acme last interaction", rendered)
        self.assertIn("Slack unavailable", rendered)

    def test_daily_plan_places_meeting_insights_and_gtd_link_before_priorities(self) -> None:
        rendered = plan_markdown(
            {
                "target_date": "2026-09-01",
                "summary": "Focus the day.",
                "gtd_link": {"label": "Open full GTD list", "url": "https://example.test/gtd"},
                "sections": {
                    "meeting_insights": ["Vasco relationship remains active."],
                    "priorities": ["Send the proposal"],
                },
            },
            {},
        )
        self.assertLess(rendered.index("Meeting Insights"), rendered.index("Open full GTD list"))
        self.assertLess(rendered.index("Open full GTD list"), rendered.index("Priorities"))

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

    def test_granular_docx_exports_override_legacy_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = {
                "artifacts": {
                    "workspace_root": temporary,
                    "path_overrides": {},
                    "exports": {
                        "docx": True,
                        "daily_plan_docx": True,
                        "agenda_docx": False,
                        "xlsx": False,
                    },
                },
                "features": {"daily_takeaways": {"max_items": 3}},
                "modules": {
                    "gtd-google-sheet": {
                        "enabled": True,
                        "spreadsheet_url": "https://example.test/gtd",
                    }
                },
                "scopes": [{"id": "acme", "name": "Acme"}],
            }
            payload = {
                "date": "2026-08-09",
                "target_date": "2026-08-10",
                "agendas": [{"title": "Weekly sync", "scope_id": "acme"}],
            }
            jobs = export_paths(payload, profile)
            self.assertEqual(len(jobs["docx"]), 1)
            self.assertEqual(jobs["docx"][0][2], "plan")
            self.assertEqual(jobs["docx"][0][1]["gtd_link"]["url"], "https://example.test/gtd")

    def test_exact_reflections_block_incomplete_close(self) -> None:
        profile = {
            "features": {
                "daily_takeaways": {
                    "enabled": True,
                    "max_items": 3,
                    "required_items": 3,
                    "incomplete_policy": "ask_until_complete",
                }
            }
        }
        payload = {"takeaways": {"well": ["one", "two"], "improve": ["one", "two", "three"]}}
        with self.assertRaisesRegex(ValueError, "ask the user"):
            validate_required_takeaways(payload, profile)
        payload["takeaways"]["well"].append("three")
        validate_required_takeaways(payload, profile)

    def test_approved_artifact_outreach_consumes_rotation_for_later_plans(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            people_path = root / "people.json"
            state_path = root / "people-state.json"
            people_path.write_text(
                '{"schema_version":1,"people":["Ben","Jen","Jason","Elle"]}',
                encoding="utf-8",
            )
            profile = {
                "features": {
                    "people_outreach": {
                        "enabled": True,
                        "daily_count": 2,
                        "selection_policy": "round_robin",
                        "duplicate_policy": "count_entries",
                        "list_path": str(people_path),
                        "state_path": str(state_path),
                    }
                }
            }
            first_payload = {
                "target_date": "2026-09-04",
                "sections": {"people_outreach": [{"text": "Ben"}, {"text": "Jen"}]},
            }
            first = prepare_people_outreach_selection(first_payload, profile)
            self.assertEqual(first["people"], ["Ben", "Jen"])
            commit_selection(profile, first, approved=True)

            second_payload = {
                "target_date": "2026-09-05",
                "sections": {"people_outreach": [{"text": "Jason"}, {"text": "Elle"}]},
            }
            second = prepare_people_outreach_selection(second_payload, profile)
            self.assertEqual(second["people"], ["Jason", "Elle"])
            self.assertEqual(second["indices"], [2, 3])

    def test_artifact_outreach_rejects_stale_displayed_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            people_path = root / "people.json"
            state_path = root / "people-state.json"
            people_path.write_text(
                '{"schema_version":1,"people":["Ben","Jen","Jason","Elle"]}',
                encoding="utf-8",
            )
            profile = {
                "features": {
                    "people_outreach": {
                        "enabled": True,
                        "daily_count": 2,
                        "selection_policy": "round_robin",
                        "duplicate_policy": "count_entries",
                        "list_path": str(people_path),
                        "state_path": str(state_path),
                    }
                }
            }
            consumed = select_people(profile, "2026-09-04", {})
            commit_selection(profile, consumed, approved=True)
            stale_payload = {
                "target_date": "2026-09-05",
                "sections": {"people_outreach": ["Ben", "Jen"]},
            }
            with self.assertRaisesRegex(ValueError, "deterministic selection"):
                prepare_people_outreach_selection(stale_payload, profile)


if __name__ == "__main__":
    unittest.main()
