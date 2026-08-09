#!/usr/bin/env python3
"""Emit normalized, scope-bound metadata for recently modified local files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from close_day_config import atomic_write_text, load_json, resolve_profile


SKIPPED_DIRECTORIES = {".git", ".svn", "__pycache__", "node_modules"}


def iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat()


def normalized_extensions(values: Iterable[str]) -> set[str]:
    result = set()
    for value in values:
        extension = str(value).strip().lower()
        if extension and not extension.startswith("."):
            extension = f".{extension}"
        if extension:
            result.add(extension)
    return result


def file_or_time_limit_reached(state: dict[str, Any], deadline: float, max_files: int) -> bool:
    if time.monotonic() >= deadline:
        state["limited_by"] = "time"
    elif state["scanned_files"] >= max_files:
        state["limited_by"] = "files"
    return state["limited_by"] is not None


def iter_files(
    root: Path,
    recursive: bool,
    state: dict[str, Any],
    deadline: float,
    max_files: int,
    max_directories: int,
) -> Iterable[Path]:
    if not recursive:
        state["scanned_directories"] += 1
        for child in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
            if file_or_time_limit_reached(state, deadline, max_files):
                return
            if child.is_file() and not child.is_symlink() and not child.name.startswith((".", "~$")):
                state["scanned_files"] += 1
                yield child
        return

    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        if file_or_time_limit_reached(state, deadline, max_files):
            return
        if state["scanned_directories"] >= max_directories:
            state["limited_by"] = "directories"
            return
        state["scanned_directories"] += 1
        dirnames[:] = sorted(
            [name for name in dirnames if name not in SKIPPED_DIRECTORIES and not name.startswith(".")],
            key=str.casefold,
        )
        for filename in sorted(filenames, key=str.casefold):
            if file_or_time_limit_reached(state, deadline, max_files):
                return
            if filename.startswith((".", "~$")):
                continue
            path = Path(directory) / filename
            if not path.is_symlink():
                state["scanned_files"] += 1
                yield path


def file_item(path: Path, root: Path, scope_id: str, stat: os.stat_result) -> dict[str, Any]:
    relative = path.relative_to(root)
    stable_input = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")
    item_id = hashlib.sha256(stable_input).hexdigest()[:24]
    return {
        "id": f"local-file:{item_id}",
        "kind": "file",
        "scope_id": scope_id,
        "title": path.name,
        "text": f"Recently modified local file: {relative} ({stat.st_size} bytes)",
        "participants": [],
        "timestamp": iso_utc(stat.st_mtime),
        "source": {
            "provider": "local-files",
            "root": str(root),
            "path": str(path),
            "relative_path": str(relative),
            "id": item_id,
        },
    }


def collect_local_files(module: dict, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    max_files = int(module.get("max_files", 200))
    max_scanned_files = int(module.get("max_scanned_files", 5000))
    max_scanned_directories = int(module.get("max_scanned_directories", 1000))
    max_scan_seconds = int(module.get("max_scan_seconds", 15))
    candidates: list[tuple[float, dict[str, Any]]] = []
    gaps: list[str] = []
    scan_stats: list[dict[str, Any]] = []

    for root_config in module.get("roots") or []:
        root = Path(root_config["path"]).expanduser()
        scope_id = root_config["scope_id"]
        if not root.is_dir():
            gaps.append(f"local-files: root does not exist or is not a directory: {root}")
            continue
        cutoff = current - timedelta(days=int(root_config.get("lookback_days", 7)))
        extensions = normalized_extensions(root_config.get("include_extensions") or [])
        state: dict[str, Any] = {
            "root": str(root),
            "scanned_files": 0,
            "scanned_directories": 0,
            "limited_by": None,
        }
        deadline = time.monotonic() + max_scan_seconds
        try:
            for path in iter_files(
                root,
                bool(root_config.get("recursive", True)),
                state,
                deadline,
                max_scanned_files,
                max_scanned_directories,
            ):
                if extensions and path.suffix.lower() not in extensions:
                    continue
                try:
                    stat = path.stat()
                except OSError as exc:
                    gaps.append(f"local-files: cannot inspect {path}: {exc}")
                    continue
                modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                if modified < cutoff:
                    continue
                candidates.append((stat.st_mtime, file_item(path, root, scope_id, stat)))
        except OSError as exc:
            gaps.append(f"local-files: cannot scan {root}: {exc}")
        if state["limited_by"]:
            gaps.append(
                f"local-files: bounded scan stopped by {state['limited_by']} limit for {root}; "
                "narrow the root or adjust scan limits"
            )
        scan_stats.append(state)

    candidates.sort(key=lambda entry: (-entry[0], entry[1]["source"]["path"].casefold()))
    truncated = len(candidates) > max_files
    return {
        "items": [item for _, item in candidates[:max_files]],
        "gaps": gaps,
        "truncated": truncated,
        "candidate_count": len(candidates),
        "scan_stats": scan_stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect recent local-file metadata for close-day.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--profile", help="Named schema-v2 profile from the private registry.")
    source.add_argument("--config", help="Path to a schema-v2 profile JSON file.")
    parser.add_argument("--config-root", help="Override the private close-day config directory.")
    parser.add_argument("--output", help="Write JSON to this path instead of stdout.")
    args = parser.parse_args()

    try:
        if args.config:
            profile = load_json(Path(args.config).expanduser())
        else:
            root = Path(args.config_root).expanduser() if args.config_root else None
            profile, _ = resolve_profile(args.profile, root)
        module = (profile.get("modules") or {}).get("local-files") or {}
        if not module.get("enabled"):
            raise ValueError("local-files is not enabled in the selected profile")
        payload = collect_local_files(module)
        rendered = json.dumps(payload, indent=2)
        if args.output:
            destination = Path(args.output).expanduser()
            atomic_write_text(destination, rendered + "\n")
        else:
            print(rendered)
        return 0 if not payload["gaps"] else 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
