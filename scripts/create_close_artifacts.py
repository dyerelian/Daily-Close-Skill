#!/usr/bin/env python3
"""Create portable close-day Markdown/JSON artifacts from an approved payload."""

from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from close_day_config import (
    atomic_write_json,
    atomic_write_text,
    export_enabled,
    load_json,
    resolve_profile,
    resolved_artifact_paths,
    validate_profile,
)
from create_agenda_docx import create_docx as create_agenda_docx
from create_daily_plan_docx import create_docx as create_daily_plan_docx
from close_payload import configured_gtd_link, normalize_payload
from people_outreach import (
    commit_selection as commit_people_outreach_selection,
    config as people_outreach_config,
    select_people,
)


def clean_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "-", value).strip(" .")
    return cleaned or "agenda"


def iso_date(value: object, field: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD)") from exc


def parse_scheduled_time(value: object, field: str, timezone_name: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone offset")
    if not timezone_name.strip():
        raise ValueError("owner.timezone must be configured")
    return parsed


def clock_minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def minute_of_day(value: datetime) -> int:
    return value.hour * 60 + value.minute


def render_clock(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(value or "").strip()
    hour = parsed.hour % 12 or 12
    suffix = "AM" if parsed.hour < 12 else "PM"
    return f"{hour}:{parsed.minute:02d} {suffix}"


def scheduled_span(item: dict[str, Any]) -> str:
    if item.get("time"):
        return str(item["time"]).strip()
    if not item.get("start"):
        return ""
    start = render_clock(item.get("start"))
    end = render_clock(item.get("end")) if item.get("end") else ""
    return f"{start}-{end}" if start and end else start


def sorted_scheduled_items(values: Any) -> list[Any]:
    def sort_key(item: Any) -> tuple[int, str]:
        if not isinstance(item, dict) or not item.get("start"):
            return (1, "")
        try:
            parsed = datetime.fromisoformat(str(item["start"]).replace("Z", "+00:00"))
        except ValueError:
            return (1, "")
        return (0, parsed.isoformat())

    return sorted(list(values or []), key=sort_key)


def label(item: Any, scopes: dict[str, str]) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return str(item)
    text = str(item.get("text") or item.get("title") or item.get("subject") or "").strip()
    when = scheduled_span(item)
    if when and text:
        text = f"{when} — {text}"
    location = str(item.get("location") or "").strip()
    if location:
        text = f"{text} ({location})"
    scope_id = item.get("scope_id")
    scope_name = scopes.get(scope_id, scope_id) if scope_id else None
    return f"[{scope_name}] {text}" if scope_name else text


def validate_planning_policy(payload: dict, profile: dict) -> None:
    policy = ((profile.get("schedule") or {}).get("planning_policy"))
    if not policy:
        return

    normalized = normalize_payload(payload)
    sections = normalized.get("sections") or {}
    timezone_name = str((profile.get("owner") or {}).get("timezone") or "UTC")
    target = iso_date(
        normalized.get("target_date") or normalized.get("date") or date.today().isoformat(),
        "target_date",
    )

    daytime = policy["daytime_window"]
    daytime_start = clock_minutes(daytime["start"])
    daytime_end = clock_minutes(daytime["end"])
    daytime_maximum = int(daytime["max_total_minutes"])
    daytime_rules = {
        (rule["scope_id"], rule["work_type"]): int(rule["max_item_minutes"])
        for rule in policy["daytime_rules"]
    }
    focused_windows = {
        scope_id: [
            (clock_minutes(window["start"]), clock_minutes(window["end"]))
            for window in windows
        ]
        for scope_id, windows in policy["focused_work_windows"].items()
    }

    meeting_ranges: list[tuple[datetime, datetime, str]] = []
    for index, item in enumerate(sections.get("meetings") or []):
        field = f"sections.meetings[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{field} must be an object when planning_policy is enabled")
        start = parse_scheduled_time(item.get("start"), f"{field}.start", timezone_name)
        end = parse_scheduled_time(item.get("end"), f"{field}.end", timezone_name)
        if end <= start:
            raise ValueError(f"{field}.end must be later than .start")
        if start.date().isoformat() != target:
            raise ValueError(f"{field}.start must fall on target_date {target}")
        meeting_ranges.append((start, end, label(item, {})))

    task_ranges: list[tuple[datetime, datetime, str]] = []
    daytime_total = 0.0
    for index, item in enumerate(sections.get("tasks") or []):
        field = f"sections.tasks[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{field} must be a structured task when planning_policy is enabled")
        if not str(item.get("text") or item.get("title") or "").strip():
            raise ValueError(f"{field}.text must be non-empty")
        scope_id = str(item.get("scope_id") or "").strip()
        work_type = str(item.get("work_type") or "").strip()
        if not scope_id:
            raise ValueError(f"{field}.scope_id is required")
        if work_type not in {"focused_work", "check_in", "personal"}:
            raise ValueError(f"{field}.work_type must be focused_work, check_in, or personal")
        start = parse_scheduled_time(item.get("start"), f"{field}.start", timezone_name)
        end = parse_scheduled_time(item.get("end"), f"{field}.end", timezone_name)
        if end <= start:
            raise ValueError(f"{field}.end must be later than .start")
        if start.date() != end.date() or start.date().isoformat() != target:
            raise ValueError(f"{field} must start and end on target_date {target}")

        duration = (end - start).total_seconds() / 60
        start_minute = minute_of_day(start)
        end_minute = minute_of_day(end)
        inside_daytime = start_minute >= daytime_start and end_minute <= daytime_end
        if inside_daytime:
            maximum = daytime_rules.get((scope_id, work_type))
            if maximum is None:
                raise ValueError(
                    f"{field} is not allowed in the configured daytime window: {scope_id}/{work_type}"
                )
            if duration > maximum:
                raise ValueError(f"{field} exceeds its {maximum}-minute daytime item limit")
            daytime_total += duration
        else:
            windows = focused_windows.get(scope_id) or []
            if not any(
                start_minute >= window_start and end_minute <= window_end
                for window_start, window_end in windows
            ):
                raise ValueError(f"{field} falls outside the configured work windows for {scope_id}")

        for meeting_start, meeting_end, meeting_label in meeting_ranges:
            if start < meeting_end and meeting_start < end:
                raise ValueError(f"{field} overlaps calendar commitment: {meeting_label}")
        for task_start, task_end, task_label in task_ranges:
            if start < task_end and task_start < end:
                raise ValueError(f"{field} overlaps scheduled task: {task_label}")
        task_ranges.append((start, end, label(item, {})))

    if daytime_total > daytime_maximum:
        raise ValueError(
            f"scheduled daytime work totals {daytime_total:g} minutes; maximum is {daytime_maximum}"
        )


def bullets(values: Any, scopes: dict[str, str]) -> list[str]:
    return [f"- {label(value, scopes)}" for value in (values or []) if label(value, scopes).strip()]


def section(lines: list[str], heading: str, values: Any, scopes: dict[str, str]) -> None:
    rendered = bullets(values, scopes)
    if not rendered:
        return
    lines.extend([f"## {heading}", "", *rendered, ""])


def takeaways(lines: list[str], payload: dict, scopes: dict[str, str]) -> None:
    value = payload.get("takeaways") or {}
    well = value.get("well") or []
    improve = value.get("improve") or []
    if not well and not improve:
        return
    lines.extend(["## Daily Takeaways", ""])
    if well:
        lines.append("**Did well**")
        lines.append("")
        lines.extend(bullets(well, scopes))
        lines.append("")
    if improve:
        lines.append("**To improve next time**")
        lines.append("")
        lines.extend(bullets(improve, scopes))
        lines.append("")


def crm_review_summary(lines: list[str], payload: dict, scopes: dict[str, str]) -> None:
    review = payload.get("crm_review") or {}
    if not review:
        return
    lines.extend(["## CRM Review", ""])
    status = str(review.get("status") or "unknown").replace("_", " ").title()
    lines.append(f"- Status: {status}")
    handler = str(review.get("handler_skill") or "").strip()
    if handler:
        lines.append(f"- Handler: {handler}")
    window = review.get("window") or {}
    if window.get("start") and window.get("end"):
        lines.append(f"- Review window: {window['start']} through {window['end']}")
    counts = review.get("counts") or {}
    if counts:
        rendered_counts = ", ".join(
            f"{key.replace('_', ' ')} {value}" for key, value in sorted(counts.items())
        )
        lines.append(f"- Changes: {rendered_counts}")
    lines.append("")
    section(lines, "CRM updates", review.get("summary_items"), scopes)
    section(lines, "CRM review flags", review.get("review_flags"), scopes)
    gaps = review.get("gaps") or []
    if gaps:
        lines.extend(["### CRM coverage gaps", ""])
        lines.extend(f"- {str(gap)}" for gap in gaps)
        lines.append("")


def plan_reflections(lines: list[str], payload: dict, scopes: dict[str, str]) -> None:
    value = payload.get("takeaways") or {}
    well = value.get("well") or []
    improve = value.get("improve") or []
    required = int(value.get("required_items") or max(len(well), len(improve), 0))
    noun = "thing" if required == 1 else "things"
    if well:
        lines.extend([f"## Yesterday — {required} {noun} I did well", ""])
        lines.extend(f"{index}. {label(item, scopes)}" for index, item in enumerate(well, 1))
        lines.append("")
    if improve:
        lines.extend([f"## Today — {required} {noun} I can improve", ""])
        lines.extend(f"{index}. {label(item, scopes)}" for index, item in enumerate(improve, 1))
        lines.append("")


def validate_required_takeaways(payload: dict, profile: dict) -> None:
    config = ((profile.get("features") or {}).get("daily_takeaways") or {})
    if not config.get("enabled", False):
        return
    required = int(config.get("required_items") or 0)
    if required <= 0 or config.get("incomplete_policy", "allow_partial") != "ask_until_complete":
        return
    takeaways_value = payload.get("takeaways") or {}
    missing = []
    for key, label_text in (("well", "things done well"), ("improve", "things to improve")):
        values = [item for item in (takeaways_value.get(key) or []) if label(item, {}).strip()]
        if len(values) != required:
            missing.append(f"{label_text}: expected exactly {required}, found {len(values)}")
    if missing:
        raise ValueError(
            "Daily Plan reflections are incomplete; ask the user before finalizing: "
            + "; ".join(missing)
        )


def prepare_people_outreach_selection(payload: dict, profile: dict) -> dict | None:
    """Validate and return the exact outreach selection displayed in the Daily Plan."""
    settings = people_outreach_config(profile)
    if not settings.get("enabled", False):
        return None
    planned = []
    for item in ((payload.get("sections") or {}).get("people_outreach") or []):
        if isinstance(item, dict):
            value = item.get("text") or item.get("title") or item.get("subject")
        else:
            value = item
        name = str(value or "").strip()
        if name:
            planned.append(name)
    if not planned:
        return None
    target = iso_date(payload.get("target_date") or payload.get("date") or date.today().isoformat(), "target_date")
    state_path_text = settings.get("state_path")
    state_path = Path(state_path_text).expanduser() if isinstance(state_path_text, str) else None
    state = load_json(state_path) if state_path and state_path.is_file() else {}
    selection = select_people(profile, target, state)
    if planned != selection.get("people"):
        raise ValueError(
            "Daily Plan people_outreach does not match the deterministic selection for "
            f"{target}: expected {selection.get('people') or []}, found {planned}"
        )
    return selection


def eod_markdown(payload: dict, scopes: dict[str, str]) -> str:
    close_date = payload.get("date") or date.today().isoformat()
    lines = [f"# End-of-Day Close — {close_date}", ""]
    takeaways(lines, payload, scopes)
    crm_review_summary(lines, payload, scopes)
    sections = payload.get("sections") or {}
    section(lines, "Meeting Insights", sections.get("meeting_insights"), scopes)
    for key, heading in (
        ("accomplished", "Accomplished"),
        ("captured", "Captured"),
        ("carried", "Carried Forward"),
        ("waiting", "Waiting On"),
        ("notes", "Notes"),
    ):
        section(lines, heading, sections.get(key), scopes)
    return "\n".join(lines).rstrip() + "\n"


def plan_markdown(payload: dict, scopes: dict[str, str]) -> str:
    payload = normalize_payload(payload)
    target = payload.get("target_date") or payload.get("date") or date.today().isoformat()
    lines = [f"# Daily Plan — {target}", ""]
    plan_reflections(lines, payload, scopes)
    summary = str(payload.get("summary") or "").strip()
    if summary:
        lines.extend([summary, ""])
    sections = payload.get("sections") or {}
    section(lines, "Meeting Insights", sections.get("meeting_insights"), scopes)
    gtd_link = payload.get("gtd_link") or {}
    if gtd_link.get("url"):
        lines.extend(
            [f"[{gtd_link.get('label') or 'Open full GTD list'}]({gtd_link['url']})", ""]
        )
    for key, heading in (
        ("priorities", "Priorities"),
        ("tasks", "Tasks"),
        ("waiting", "Waiting On"),
        ("meetings", "Meetings"),
        ("people_outreach", "People Outreach"),
    ):
        values = sections.get(key)
        if key in {"tasks", "meetings"}:
            values = sorted_scheduled_items(values)
        section(lines, heading, values, scopes)
    return "\n".join(lines).rstrip() + "\n"


def task_markdown(payload: dict, scopes: dict[str, str]) -> str:
    payload = normalize_payload(payload)
    target = payload.get("target_date") or payload.get("date") or date.today().isoformat()
    lines = [f"# Tasks — {target}", ""]
    sections = payload.get("sections") or {}
    tasks = sorted_scheduled_items(sections.get("tasks")) + (sections.get("carried") or [])
    lines.extend(f"- [ ] {label(item, scopes)}" for item in tasks if label(item, scopes).strip())
    return "\n".join(lines).rstrip() + "\n"


def agenda_markdown(agenda: dict, scopes: dict[str, str]) -> str:
    title = label({"text": agenda.get("title") or "Meeting Agenda", "scope_id": agenda.get("scope_id")}, scopes)
    lines = [f"# {title}", ""]
    recap = agenda.get("last_meeting_recap") or {}
    if recap:
        lines.extend(["## Last meeting recap", ""])
        summary = str(recap.get("summary") or "No prior meeting found.").strip()
        lines.extend([summary, ""])
        for key, heading in (
            ("follow_ups", "Open follow-ups"),
            ("decisions", "Decisions"),
            ("talking_points", "Suggested talking points"),
        ):
            section(lines, heading, recap.get(key), scopes)
    section(lines, "Agenda", agenda.get("items"), scopes)
    return "\n".join(lines).rstrip() + "\n"


def build_outputs(payload: dict, profile: dict) -> dict[Path, str | dict]:
    payload = normalize_payload(payload)
    validate_planning_policy(payload, profile)
    if not payload.get("gtd_link"):
        payload["gtd_link"] = configured_gtd_link(profile)
    paths = {key: Path(value) for key, value in resolved_artifact_paths(profile["artifacts"]).items()}
    scopes = {scope["id"]: scope["name"] for scope in profile.get("scopes") or []}
    close_date = iso_date(payload.get("date") or date.today().isoformat(), "date")
    target = iso_date(payload.get("target_date") or close_date, "target_date")
    outputs: dict[Path, str | dict] = {
        paths["logs"] / f"EOD {close_date}.md": eod_markdown(payload, scopes),
        paths["plans"] / f"Daily Plan {target}.md": plan_markdown(payload, scopes),
        paths["tasks"] / f"Tasks {target}.md": task_markdown(payload, scopes),
        paths["state"] / f"{close_date}-close.json": payload,
    }
    for agenda in payload.get("agendas") or []:
        if not isinstance(agenda, dict):
            continue
        title = clean_filename(str(agenda.get("title") or "Meeting Agenda"))
        outputs[paths["agendas"] / target / f"{title}.md"] = agenda_markdown(agenda, scopes)
    return outputs


def export_paths(payload: dict, profile: dict) -> dict[str, list[tuple[Path, dict, str]] | Path]:
    payload = normalize_payload(payload)
    validate_planning_policy(payload, profile)
    if not payload.get("gtd_link"):
        payload["gtd_link"] = configured_gtd_link(profile)
    paths = {key: Path(value) for key, value in resolved_artifact_paths(profile["artifacts"]).items()}
    close_date = iso_date(payload.get("date") or date.today().isoformat(), "date")
    target = iso_date(payload.get("target_date") or close_date, "target_date")
    exports = (profile.get("artifacts") or {}).get("exports") or {}
    scope_names = {scope["id"]: scope["name"] for scope in profile.get("scopes") or []}

    def labeled(values: Any) -> list[str]:
        return [label(value, scope_names) for value in (values or []) if label(value, scope_names).strip()]

    def labeled_meetings(values: Any) -> list[object]:
        rendered = []
        for value in values or []:
            if not isinstance(value, dict):
                rendered.append(value)
                continue
            item = copy.deepcopy(value)
            key = "title" if item.get("title") else "subject" if item.get("subject") else "title"
            item[key] = label({"text": item.get(key) or "Meeting", "scope_id": item.get("scope_id")}, scope_names)
            rendered.append(item)
        return rendered

    agenda_exports = []
    for agenda in payload.get("agendas") or []:
        if not isinstance(agenda, dict):
            continue
        item = copy.deepcopy(agenda)
        item["title"] = label({"text": item.get("title") or "Meeting Agenda", "scope_id": item.get("scope_id")}, scope_names)
        agenda_exports.append(item)
    result: dict[str, list[tuple[Path, dict, str]] | Path] = {"docx": []}
    if export_enabled(exports, "daily_plan_docx"):
        features = profile.get("features") or {}
        sections = payload.get("sections") or {}
        if payload.get("daily_plan"):
            daily_plan = copy.deepcopy(payload["daily_plan"])
        else:
            takeaway_value = payload.get("takeaways") or {}
            takeaway_limit = int(((features.get("daily_takeaways") or {}).get("max_items") or 3))
            daily_plan = {
                "date": target,
                "summary": payload.get("summary"),
                "meeting_insights": labeled(sections.get("meeting_insights")),
                "gtd_link": copy.deepcopy(payload.get("gtd_link")),
                "takeaways": {
                    "source_day": takeaway_value.get("source_day") or close_date,
                    "well": labeled(takeaway_value.get("well"))[:takeaway_limit],
                    "improve": labeled(takeaway_value.get("improve"))[:takeaway_limit],
                    "required_items": int(
                        ((features.get("daily_takeaways") or {}).get("required_items") or 0)
                    ),
                },
                "daily_big_3": labeled(sections.get("priorities")),
                "top_actions": labeled(sorted_scheduled_items(sections.get("tasks"))),
                "other_actions": labeled(sections.get("waiting")),
                "people_outreach": labeled(sections.get("people_outreach")),
                "meetings": labeled_meetings(sorted_scheduled_items(sections.get("meetings"))),
            }
        daily_plan["page_numbers"] = bool(features.get("docx_page_numbers", True))
        daily_plan.setdefault("takeaways", {}).setdefault(
            "required_items",
            int(((features.get("daily_takeaways") or {}).get("required_items") or 0)),
        )
        result["docx"].append((paths["plans"] / f"Daily Plan {target}.docx", daily_plan, "plan"))
    if export_enabled(exports, "agenda_docx"):
        for agenda in agenda_exports:
            if not isinstance(agenda, dict):
                continue
            title = clean_filename(str(agenda.get("title") or "Meeting Agenda"))
            result["docx"].append((paths["agendas"] / target / f"{title}.docx", agenda, "agenda"))
    if exports.get("xlsx"):
        result["xlsx"] = paths["tasks"] / f"Tasks {target}.xlsx"
    return result


def create_task_xlsx(payload: dict, profile: dict, output: Path) -> None:
    payload = normalize_payload(payload)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError as exc:
        raise RuntimeError("XLSX export requires openpyxl") from exc
    scopes = {scope["id"]: scope["name"] for scope in profile.get("scopes") or []}
    tasks = ((payload.get("sections") or {}).get("tasks") or []) + ((payload.get("sections") or {}).get("carried") or [])
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Tasks"
    sheet.append(["Scope", "Task", "Status", "Due Date", "Source"])
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for item in tasks:
        if isinstance(item, dict):
            scope_id = item.get("scope_id")
            source = item.get("source") or ""
            if isinstance(source, dict):
                source = ":".join(
                    str(value) for value in (source.get("provider"), source.get("id")) if value
                )
            sheet.append([
                scopes.get(scope_id, scope_id or ""),
                item.get("text") or item.get("title") or "",
                item.get("status") or "Not Started",
                item.get("due_date") or "",
                source,
            ])
        else:
            sheet.append(["", str(item), "Not Started", "", ""])
    sheet.freeze_panes = "A2"
    for column, width in {"A": 22, "B": 60, "C": 18, "D": 16, "E": 30}.items():
        sheet.column_dimensions[column].width = width
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create portable close-day artifacts.")
    parser.add_argument("--input", required=True, help="Approved close payload JSON.")
    parser.add_argument("--profile", help="Profile id from the local registry.")
    parser.add_argument("--profile-file", help="Explicit schema-v2 profile JSON path.")
    parser.add_argument("--config-root", help="Override the private config directory.")
    parser.add_argument("--approved", action="store_true", help="Required to write artifacts.")
    parser.add_argument("--dry-run", action="store_true", help="Print proposed files without writing.")
    args = parser.parse_args()

    if args.profile_file:
        profile = load_json(Path(args.profile_file).expanduser())
    else:
        profile, _ = resolve_profile(args.profile, Path(args.config_root).expanduser() if args.config_root else None)
    errors, _ = validate_profile(profile)
    if errors:
        raise ValueError("invalid profile: " + "; ".join(errors))
    payload = load_json(Path(args.input).expanduser())
    validate_required_takeaways(payload, profile)
    validate_planning_policy(payload, profile)
    outreach_selection = prepare_people_outreach_selection(payload, profile)
    outputs = build_outputs(payload, profile)
    exports = export_paths(payload, profile)
    export_files = [path for path, _, _ in exports.get("docx", [])]
    if exports.get("xlsx"):
        export_files.append(exports["xlsx"])
    if args.dry_run:
        print(json.dumps({"files": [str(path) for path in [*outputs, *export_files]]}, indent=2))
        return 0
    if not args.approved:
        parser.error("artifact writes require --approved (use --dry-run to preview)")
    if not (profile.get("permissions") or {}).get("local_artifact_writes_enabled", False):
        parser.error("profile does not permit local artifact writes")
    existing = [path for path in [*outputs, *export_files] if path.exists()]
    if existing:
        raise FileExistsError(
            "refusing to overwrite existing artifact(s): " + ", ".join(str(path) for path in existing)
        )
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict):
            atomic_write_json(path, content)
        else:
            atomic_write_text(path, content)
    for path, data, kind in exports.get("docx", []):
        if kind == "agenda":
            create_agenda_docx(data, path)
        else:
            create_daily_plan_docx(data, path)
    if exports.get("xlsx"):
        create_task_xlsx(payload, profile, exports["xlsx"])
    result = {"written": [str(path) for path in [*outputs, *export_files]]}
    if outreach_selection:
        outreach_state_path = commit_people_outreach_selection(
            profile, outreach_selection, approved=True
        )
        result["people_outreach_state"] = str(outreach_state_path)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
