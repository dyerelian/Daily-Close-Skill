"""Deterministic, private people-outreach selection for close-day."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from close_day_config import atomic_write_json, load_json, resolve_profile


def config(profile: dict[str, Any]) -> dict[str, Any]:
    return ((profile.get("features") or {}).get("people_outreach") or {})


def load_people(profile: dict[str, Any]) -> list[str]:
    settings = config(profile)
    path_text = settings.get("list_path")
    if not isinstance(path_text, str) or not path_text.strip():
        raise ValueError("features.people_outreach.list_path must be configured")
    path = Path(path_text).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"people list does not exist: {path}")
    data = load_json(path)
    people = data.get("people") if isinstance(data, dict) else None
    if not isinstance(people, list) or any(not isinstance(item, str) or not item.strip() for item in people):
        raise ValueError("people list must contain a non-empty people array of strings")
    if len(people) < 2:
        raise ValueError("people list must contain at least two entries")
    return people


def select_people(profile: dict[str, Any], target_date: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = config(profile)
    if not settings.get("enabled", False):
        return {"target_date": target_date, "people": [], "indices": [], "next_index": 0}
    people = load_people(profile)
    count = int(settings.get("daily_count", 2))
    if count < 1 or count > len(people):
        raise ValueError(f"people_outreach.daily_count must be between 1 and {len(people)}")
    state = state or {}
    assignments = state.get("assignments") or {}
    prior = assignments.get(target_date)
    if isinstance(prior, dict) and isinstance(prior.get("indices"), list):
        indices = [int(index) for index in prior["indices"]]
        return {"target_date": target_date, "indices": indices, "people": [people[index] for index in indices], "next_index": state.get("next_index", 0)}
    start = int(state.get("next_index") or 0) % len(people)
    indices = [(start + offset) % len(people) for offset in range(count)]
    return {
        "target_date": target_date,
        "indices": indices,
        "people": [people[index] for index in indices],
        "next_index": (start + count) % len(people),
    }


def commit_selection(profile: dict[str, Any], selection: dict[str, Any], approved: bool = False) -> Path:
    if not approved:
        raise PermissionError("people outreach state update requires approval")
    settings = config(profile)
    path_text = settings.get("state_path")
    if not isinstance(path_text, str) or not path_text.strip():
        raise ValueError("features.people_outreach.state_path must be configured")
    path = Path(path_text).expanduser()
    state = load_json(path) if path.is_file() else {"schema_version": 1, "next_index": 0, "assignments": {}}
    assignments = state.setdefault("assignments", {})
    assignments[str(selection["target_date"])] = {
        "indices": list(selection.get("indices") or []),
        "people": list(selection.get("people") or []),
    }
    state["next_index"] = int(selection.get("next_index") or 0)
    state["schema_version"] = 1
    atomic_write_json(path, state)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or commit close-day people outreach selection.")
    parser.add_argument("command", choices=("preview", "commit"))
    parser.add_argument("--profile", default=None)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--config-root")
    parser.add_argument("--selection")
    parser.add_argument("--approved", action="store_true")
    args = parser.parse_args()
    profile, _ = resolve_profile(args.profile, Path(args.config_root).expanduser() if args.config_root else None)
    if args.command == "preview":
        state_path = Path(config(profile).get("state_path", "")).expanduser()
        state = load_json(state_path) if state_path.is_file() else {}
        print(json.dumps(select_people(profile, date.fromisoformat(args.target_date).isoformat(), state), ensure_ascii=False, indent=2))
        return 0
    if not args.selection:
        parser.error("--selection is required for commit")
    selection = load_json(Path(args.selection).expanduser())
    print(json.dumps({"state": str(commit_selection(profile, selection, args.approved))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
