#!/usr/bin/env python3
"""Classify normalized close-day evidence into configured profile scopes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from close_day_config import (
    atomic_write_text,
    classify_items,
    load_json,
    resolve_profile,
    validate_profile,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Route close-day evidence into profile scopes.")
    parser.add_argument("--input", required=True, help="JSON array or object with an items array.")
    parser.add_argument("--profile", help="Profile id from the local registry.")
    parser.add_argument("--profile-file", help="Explicit schema-v2 profile JSON path.")
    parser.add_argument("--config-root", help="Override the private close-day config directory.")
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args()

    if bool(args.profile) and bool(args.profile_file):
        parser.error("use --profile or --profile-file, not both")
    if args.profile_file:
        profile = load_json(Path(args.profile_file).expanduser())
    else:
        profile, _ = resolve_profile(args.profile, Path(args.config_root).expanduser() if args.config_root else None)
    errors, _ = validate_profile(profile)
    if errors:
        raise ValueError("invalid profile: " + "; ".join(errors))

    payload = load_json(Path(args.input).expanduser())
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("input must be an array of objects or an object with an items array")
    result = classify_items(items, profile)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        destination = Path(args.output).expanduser()
        atomic_write_text(destination, rendered)
    else:
        sys.stdout.write(rendered)
    return 2 if result["requires_resolution"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
