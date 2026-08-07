#!/usr/bin/env python3
"""Validate close-day module manifests and a daily-close config."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from close_day_config import SCHEMA_VERSION, validate_profile


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "modules"

REQUIRED_MANIFEST_FIELDS = {
    "id",
    "display_name",
    "description",
    "required_connectors",
    "read_sources",
    "write_targets",
    "config_schema",
    "onboarding",
    "enabled_by_default",
    "proposal_output_type",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def get_dotted(data: dict, dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def type_matches(value: Any, expected: Any) -> bool:
    if expected is None:
        return True
    expected_types = expected if isinstance(expected, list) else [expected]
    actual = json_type(value)
    if actual == "integer" and "number" in expected_types:
        return True
    return actual in expected_types


def load_manifests(errors: list[str]) -> dict[str, dict]:
    manifests: dict[str, dict] = {}
    for path in sorted(MODULE_DIR.glob("*.json")):
        try:
            manifest = load_json(path)
        except Exception as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
            continue
        missing = sorted(REQUIRED_MANIFEST_FIELDS - set(manifest))
        if missing:
            errors.append(f"{path}: missing manifest fields: {', '.join(missing)}")
        module_id = manifest.get("id")
        if not isinstance(module_id, str) or not module_id:
            errors.append(f"{path}: id must be a non-empty string")
            continue
        if module_id in manifests:
            errors.append(f"{path}: duplicate module id {module_id}")
        if path.stem != module_id:
            errors.append(f"{path}: filename stem must match id {module_id}")
        for field in ("required_connectors", "read_sources", "write_targets"):
            if not isinstance(manifest.get(field), list):
                errors.append(f"{path}: {field} must be a list")
        schema = manifest.get("config_schema")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            errors.append(f"{path}: config_schema must be an object schema")
        onboarding = manifest.get("onboarding")
        if not isinstance(onboarding, dict):
            errors.append(f"{path}: onboarding must be an object")
        else:
            for field in ("question", "setup_questions", "connector_probes", "required_artifacts", "config_keys"):
                if field not in onboarding:
                    errors.append(f"{path}: onboarding missing {field}")
        manifests[module_id] = manifest
    return manifests


def validate_module_config(
    module_id: str,
    manifest: dict,
    config: dict,
    errors: list[str],
) -> None:
    module_config = (config.get("modules") or {}).get(module_id, {})
    if not isinstance(module_config, dict):
        errors.append(f"modules.{module_id} must be an object")
        return
    schema = manifest.get("config_schema") or {}
    required = schema.get("required") or []
    properties = schema.get("properties") or {}
    for key in required:
        if key not in module_config:
            errors.append(f"modules.{module_id}: missing required key {key}")
    for key, value in module_config.items():
        if key not in properties:
            continue
        expected = properties[key].get("type")
        if not type_matches(value, expected):
            errors.append(
                f"modules.{module_id}.{key}: expected {expected}, got {json_type(value)}"
            )


def validate_scope_exclusions(config: dict, errors: list[str]) -> None:
    exclusions = config.get("scope_exclusions")
    if exclusions is None:
        return
    if not isinstance(exclusions, dict):
        errors.append("scope_exclusions must be an object")
        return

    match_mode = exclusions.get("match_mode", "case_insensitive_term")
    if match_mode != "case_insensitive_term":
        errors.append(
            "scope_exclusions.match_mode must be case_insensitive_term"
        )

    topics = exclusions.get("topics")
    if not isinstance(topics, list):
        errors.append("scope_exclusions.topics must be an array")
        return

    for index, topic in enumerate(topics):
        label = f"scope_exclusions.topics[{index}]"
        if not isinstance(topic, dict):
            errors.append(f"{label} must be an object")
            continue
        name = topic.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{label}.name must be a non-empty string")
        terms = topic.get("match_terms")
        if not isinstance(terms, list) or not terms:
            errors.append(f"{label}.match_terms must be a non-empty array")
        elif any(not isinstance(term, str) or not term.strip() for term in terms):
            errors.append(f"{label}.match_terms must contain non-empty strings")
        reason = topic.get("reason")
        if reason is not None and not isinstance(reason, str):
            errors.append(f"{label}.reason must be a string when provided")


def validate_config(config_path: Path, strict_paths: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    manifests = load_manifests(errors)

    try:
        config = load_json(config_path)
    except Exception as exc:
        return [f"{config_path}: invalid JSON: {exc}"], warnings

    if config.get("schema_version") == SCHEMA_VERSION:
        profile_errors, profile_warnings = validate_profile(config, strict_paths=strict_paths)
        errors.extend(profile_errors)
        warnings.extend(profile_warnings)
        enabled = config.get("enabled_modules") or []
        unknown = sorted(set(enabled) - set(manifests))
        if unknown:
            errors.append(f"enabled_modules contains unknown module ids: {', '.join(unknown)}")
        for module_id in sorted(set(enabled) & set(manifests)):
            validate_module_config(module_id, manifests[module_id], config, errors)
        return errors, warnings

    for key in ("profile_name", "owner", "write_mode", "enabled_modules"):
        if key not in config:
            errors.append(f"config missing required key: {key}")

    validate_scope_exclusions(config, errors)

    enabled = config.get("enabled_modules")
    if not isinstance(enabled, list):
        errors.append("enabled_modules must be a list")
        enabled = []

    enabled_set = set(enabled)
    unknown = sorted(enabled_set - set(manifests))
    if unknown:
        errors.append(f"enabled_modules contains unknown module ids: {', '.join(unknown)}")

    connectors = config.get("connectors") or {}
    if not isinstance(connectors, dict):
        errors.append("connectors must be an object")
        connectors = {}

    write_mode = config.get("write_mode") or {}
    writes_enabled = bool(write_mode.get("enabled"))

    for module_id in sorted(enabled_set & set(manifests)):
        manifest = manifests[module_id]
        validate_module_config(module_id, manifest, config, errors)
        for connector in manifest.get("required_connectors") or []:
            if str(connector).startswith("local:"):
                continue
            if connector not in connectors:
                warnings.append(f"{module_id}: connector {connector} not configured")
        if manifest.get("write_targets") and not writes_enabled:
            warnings.append(f"{module_id}: write targets present but write_mode.enabled is false")

    path_checks = {
        "paths.gtd_workbook": get_dotted(config, "paths.gtd_workbook"),
        "paths.daily_plan_dir": get_dotted(config, "paths.daily_plan_dir"),
        "paths.eod_log_dir": get_dotted(config, "paths.eod_log_dir"),
        "paths.agenda_dir": get_dotted(config, "paths.agenda_dir"),
        "paths.add_gtd_items_script": get_dotted(config, "paths.add_gtd_items_script"),
        "paths.agenda_creator_script": get_dotted(config, "paths.agenda_creator_script"),
        "crm.workbook_path": get_dotted(config, "crm.workbook_path"),
    }
    for label, value in path_checks.items():
        if value in (None, ""):
            warnings.append(f"{label}: not set")
            continue
        path = resolve(str(value))
        if strict_paths and not path.exists():
            errors.append(f"{label}: path does not exist: {path}")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate close-day config and module manifests.")
    parser.add_argument("--config", default="config/daily-close.example.json")
    parser.add_argument("--strict-paths", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config_path = resolve(args.config)
    errors, warnings = validate_config(config_path, args.strict_paths)
    if args.json:
        print(json.dumps({"errors": errors, "warnings": warnings}, indent=2))
    else:
        for warning in warnings:
            print(f"warning: {warning}")
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        if not errors:
            print(f"validated: {config_path}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
