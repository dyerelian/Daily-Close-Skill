#!/usr/bin/env python3
"""List close-day module manifests and optional config enablement."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from close_day_config import resolve_profile


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "modules"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def module_manifests() -> list[dict]:
    modules = []
    for path in sorted(MODULE_DIR.glob("*.json")):
        data = load_json(path)
        data["_path"] = str(path.relative_to(ROOT))
        modules.append(data)
    return modules


def load_enabled(config_path: str | None) -> set[str]:
    if not config_path:
        return set()
    path = Path(config_path)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    config = load_json(path)
    return set(config.get("enabled_modules") or [])


def print_table(modules: list[dict], enabled: set[str]) -> None:
    rows = []
    for module in modules:
        enabled_mark = "yes" if module.get("id") in enabled else "no"
        rows.append(
            [
                module.get("id", ""),
                enabled_mark if enabled else str(module.get("enabled_by_default", False)).lower(),
                ",".join(module.get("required_connectors") or []),
                module.get("proposal_output_type", ""),
            ]
        )
    headers = ["id", "enabled", "connectors", "proposal_output_type"]
    widths = [
        max(len(str(row[i])) for row in rows + [headers])
        for i in range(len(headers))
    ]
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(str(row[i]).ljust(widths[i]) for i in range(len(row))))


def main() -> int:
    parser = argparse.ArgumentParser(description="List close-day modules.")
    parser.add_argument("--config", help="Config JSON to use for enabled status.")
    parser.add_argument("--profile", help="Named schema-v2 profile from the private registry.")
    parser.add_argument("--config-root", help="Override the private close-day config directory.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    try:
        modules = module_manifests()
        if args.config:
            enabled = load_enabled(args.config)
        elif args.profile or args.config_root:
            profile, _ = resolve_profile(
                args.profile,
                Path(args.config_root).expanduser() if args.config_root else None,
            )
            enabled = set(profile.get("enabled_modules") or [])
        else:
            enabled = set()
        if args.json:
            payload = {"modules": modules, "enabled_modules": sorted(enabled)}
            print(json.dumps(payload, indent=2))
        else:
            print_table(modules, enabled)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
