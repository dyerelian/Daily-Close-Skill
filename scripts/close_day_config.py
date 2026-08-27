#!/usr/bin/env python3
"""Shared schema-v2 profile, routing, and filesystem helpers for close-day."""

from __future__ import annotations

import json
import os
import platform
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 2
REGISTRY_FILENAME = "registry.json"


def slugify(value: str, fallback: str = "profile") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or fallback


def default_config_root() -> Path:
    """Return an OS-appropriate directory for private close-day configuration."""
    override = os.environ.get("CLOSE_DAY_CONFIG_HOME")
    if override:
        return Path(override).expanduser()
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "close-day"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "close-day"
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".config") / "close-day"


def registry_path(config_root: Path | None = None) -> Path:
    return (config_root or default_config_root()) / REGISTRY_FILENAME


def profiles_dir(config_root: Path | None = None) -> Path:
    return (config_root or default_config_root()) / "profiles"


def profile_path(profile_id: str, config_root: Path | None = None) -> Path:
    return profiles_dir(config_root) / f"{slugify(profile_id)}.json"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON without exposing a partially-written configuration file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def derived_artifact_paths(workspace_root: str | Path) -> dict[str, str]:
    root = Path(workspace_root).expanduser()
    return {
        "plans": str(root / "Plans"),
        "agendas": str(root / "Agendas"),
        "tasks": str(root / "Tasks"),
        "logs": str(root / "Logs"),
        "state": str(root / "State"),
    }


def resolved_artifact_paths(artifacts: dict) -> dict[str, str]:
    root = Path(artifacts.get("workspace_root") or "close-day-workspace").expanduser()
    derived = derived_artifact_paths(root)
    overrides = artifacts.get("path_overrides") or {}
    resolved = {}
    for key, value in derived.items():
        override = overrides.get(key)
        if not override:
            resolved[key] = value
            continue
        path = Path(override).expanduser()
        resolved[key] = str(path if path.is_absolute() else root / path)
    return resolved


def export_enabled(exports: dict, export_name: str) -> bool:
    """Resolve granular DOCX exports while preserving legacy ``docx`` profiles."""
    if export_name in exports:
        return bool(exports[export_name])
    if export_name in {"daily_plan_docx", "agenda_docx"}:
        return bool(exports.get("docx", False))
    return bool(exports.get(export_name, False))


def default_registry(default_profile_id: str | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "default_profile_id": default_profile_id,
        "profiles": [],
    }


def load_registry(config_root: Path | None = None) -> dict:
    path = registry_path(config_root)
    if not path.exists():
        return default_registry()
    return load_json(path)


def register_profile(profile: dict, config_root: Path | None = None, make_default: bool = False) -> Path:
    root = (config_root or default_config_root()).expanduser().resolve()
    profile_id = profile["profile"]["id"]
    destination = profile_path(profile_id, root)
    atomic_write_json(destination, profile)
    registry = load_registry(root)
    registry["schema_version"] = SCHEMA_VERSION
    records = [record for record in registry.get("profiles") or [] if record.get("id") != profile_id]
    records.append({"id": profile_id, "name": profile["profile"]["name"], "path": str(destination)})
    registry["profiles"] = sorted(records, key=lambda record: record["id"])
    if make_default or not registry.get("default_profile_id"):
        registry["default_profile_id"] = profile_id
    atomic_write_json(registry_path(root), registry)
    return destination


def resolve_profile(profile_id: str | None = None, config_root: Path | None = None) -> tuple[dict, Path]:
    root = (config_root or default_config_root()).expanduser().resolve()
    registry = load_registry(root)
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"profile registry schema {registry.get('schema_version')} is unsupported; expected {SCHEMA_VERSION}"
        )
    selected = profile_id or registry.get("default_profile_id")
    if not selected:
        raise FileNotFoundError("No default close-day profile is configured.")
    for record in registry.get("profiles") or []:
        if record.get("id") == selected:
            path = Path(record.get("path") or profile_path(selected, root)).expanduser()
            if not path.is_absolute():
                path = root / path
            return load_json(path), path
    path = profile_path(selected, root)
    if path.exists():
        return load_json(path), path
    raise FileNotFoundError(f"close-day profile not found: {selected}")


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_profile(profile: dict, strict_paths: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if profile.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    metadata = profile.get("profile")
    if not isinstance(metadata, dict):
        errors.append("profile must be an object")
    else:
        if not _nonempty_string(metadata.get("id")):
            errors.append("profile.id must be a non-empty string")
        elif metadata.get("id") != slugify(metadata["id"]):
            errors.append("profile.id must use lowercase letters, digits, and hyphens")
        if not _nonempty_string(metadata.get("name")):
            errors.append("profile.name must be a non-empty string")

    owner = profile.get("owner")
    if not isinstance(owner, dict):
        errors.append("owner must be an object")
    else:
        for key in ("name", "timezone"):
            if not _nonempty_string(owner.get(key)):
                errors.append(f"owner.{key} must be a non-empty string")

    schedule = profile.get("schedule") or {}
    workdays = schedule.get("workdays")
    allowed_days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
    if not isinstance(workdays, list) or not workdays or any(day not in allowed_days for day in workdays):
        errors.append("schedule.workdays must be a non-empty array of weekday names")
    close_time = schedule.get("close_out_time")
    if not _nonempty_string(close_time) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", close_time):
        errors.append("schedule.close_out_time must use 24-hour HH:MM")

    scopes = profile.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        errors.append("scopes must be a non-empty array")
        scopes = []
    seen: set[str] = set()
    bindings_seen: dict[str, str] = {}
    for index, scope in enumerate(scopes):
        label = f"scopes[{index}]"
        if not isinstance(scope, dict):
            errors.append(f"{label} must be an object")
            continue
        scope_id = scope.get("id")
        if not _nonempty_string(scope_id):
            errors.append(f"{label}.id must be a non-empty string")
        elif scope_id in seen:
            errors.append(f"duplicate scope id: {scope_id}")
        else:
            seen.add(scope_id)
        if scope.get("type") not in {"personal", "organization"}:
            errors.append(f"{label}.type must be personal or organization")
        if not _nonempty_string(scope.get("name")):
            errors.append(f"{label}.name must be a non-empty string")
        for key in ("aliases", "domains", "include_terms", "exclude_terms", "source_bindings"):
            value = scope.get(key, [])
            if not isinstance(value, list) or any(not _nonempty_string(item) for item in value):
                errors.append(f"{label}.{key} must be an array of non-empty strings")
        for binding in scope.get("source_bindings") or []:
            normalized = binding.casefold()
            if normalized in bindings_seen and bindings_seen[normalized] != scope_id:
                errors.append(
                    f"source binding is assigned to multiple scopes: {binding} "
                    f"({bindings_seen[normalized]}, {scope_id})"
                )
            else:
                bindings_seen[normalized] = scope_id

    routing = profile.get("routing") or {}
    if routing.get("unclassified_policy") != "pause_and_ask":
        errors.append("routing.unclassified_policy must be pause_and_ask")
    exclusions = routing.get("global_exclusions", [])
    if not isinstance(exclusions, list):
        errors.append("routing.global_exclusions must be an array")
    else:
        for index, exclusion in enumerate(exclusions):
            if not isinstance(exclusion, dict) or not _nonempty_string(exclusion.get("name")):
                errors.append(f"routing.global_exclusions[{index}] must have a non-empty name")
                continue
            terms = exclusion.get("match_terms")
            if not isinstance(terms, list) or not terms or any(not _nonempty_string(term) for term in terms):
                errors.append(f"routing.global_exclusions[{index}].match_terms must be non-empty strings")

    artifacts = profile.get("artifacts")
    if not isinstance(artifacts, dict) or not _nonempty_string(artifacts.get("workspace_root")):
        errors.append("artifacts.workspace_root must be a non-empty string")
    else:
        canonical = artifacts.get("canonical") or {}
        if not canonical.get("markdown") or not canonical.get("json"):
            errors.append("artifacts.canonical must enable markdown and json")
        overrides = artifacts.get("path_overrides") or {}
        if not isinstance(overrides, dict):
            errors.append("artifacts.path_overrides must be an object")
        else:
            unknown_overrides = sorted(set(overrides) - {"plans", "agendas", "tasks", "logs", "state"})
            if unknown_overrides:
                errors.append(f"unknown artifact path overrides: {', '.join(unknown_overrides)}")
            for key, value in overrides.items():
                if not _nonempty_string(value):
                    errors.append(f"artifacts.path_overrides.{key} must be a non-empty string")
        exports = artifacts.get("exports") or {}
        if not isinstance(exports, dict):
            errors.append("artifacts.exports must be an object")
            exports = {}
        else:
            for key in ("docx", "daily_plan_docx", "agenda_docx", "xlsx"):
                if key in exports and not isinstance(exports[key], bool):
                    errors.append(f"artifacts.exports.{key} must be a boolean")
        for name, path_text in resolved_artifact_paths(artifacts).items():
            path = Path(path_text)
            if strict_paths and not path.exists():
                errors.append(f"artifact path does not exist ({name}): {path}")
            elif not path.exists():
                warnings.append(f"artifact path does not exist yet ({name}): {path}")

    permissions = profile.get("permissions") or {}
    for key in (
        "proposal_required",
        "external_writes_enabled",
        "local_artifact_writes_enabled",
        "jira_ticket_approval_required",
        "crm_writes_enabled",
    ):
        if not isinstance(permissions.get(key), bool):
            errors.append(f"permissions.{key} must be a boolean")
    if not permissions.get("proposal_required", False):
        errors.append("permissions.proposal_required must be true")
    if not permissions.get("jira_ticket_approval_required", False):
        errors.append("permissions.jira_ticket_approval_required must be true")
    if "email_delivery_enabled" in permissions and not isinstance(
        permissions.get("email_delivery_enabled"), bool
    ):
        errors.append("permissions.email_delivery_enabled must be a boolean")
    for key in ("gtd_writes_enabled", "jira_writes_enabled"):
        if key in permissions and not isinstance(permissions.get(key), bool):
            errors.append(f"permissions.{key} must be a boolean")

    enabled = profile.get("enabled_modules")
    modules = profile.get("modules")
    if not isinstance(enabled, list):
        errors.append("enabled_modules must be an array")
        enabled = []
    if not isinstance(modules, dict):
        errors.append("modules must be an object")
        modules = {}
    for module_id in enabled:
        if module_id not in modules:
            errors.append(f"enabled module missing config: {module_id}")
        elif not (modules.get(module_id) or {}).get("enabled", False):
            errors.append(f"enabled module is not marked enabled: {module_id}")

    for module_id, supported in (("mail-sweep", {"gmail", "outlook"}), ("calendar-sweep", {"google", "outlook"})):
        module = modules.get(module_id) or {}
        for index, provider in enumerate(module.get("providers") or []):
            label = f"modules.{module_id}.providers[{index}]"
            if not isinstance(provider, dict):
                errors.append(f"{label} must be an object")
                continue
            if provider.get("provider") not in supported:
                errors.append(f"{label}.provider is not supported")
            scope_ids = provider.get("scope_ids")
            if not isinstance(scope_ids, list) or not scope_ids:
                errors.append(f"{label}.scope_ids must be a non-empty array")
            elif any(not _nonempty_string(scope_id) for scope_id in scope_ids):
                errors.append(f"{label}.scope_ids must contain non-empty strings")
            else:
                unknown_scopes = sorted(set(scope_ids) - seen)
                if unknown_scopes:
                    errors.append(f"{label}.scope_ids contains unknown scopes: {', '.join(unknown_scopes)}")

    jira = modules.get("jira-sweep") or {}
    if jira.get("enabled"):
        if not isinstance(jira.get("connector_configured"), bool):
            errors.append("modules.jira-sweep.connector_configured must be a boolean")
        queries = jira.get("queries")
        if not isinstance(queries, list) or not queries:
            errors.append("modules.jira-sweep.queries must be a non-empty array")
        else:
            for index, query in enumerate(queries):
                label = f"modules.jira-sweep.queries[{index}]"
                if not isinstance(query, dict):
                    errors.append(f"{label} must be an object")
                    continue
                if not _nonempty_string(query.get("name")):
                    errors.append(f"{label}.name must be a non-empty string")
                if not _nonempty_string(query.get("jql")):
                    errors.append(f"{label}.jql must be a non-empty string")
                if query.get("scope_id") not in seen:
                    errors.append(f"{label}.scope_id must reference a configured scope")
                limit = query.get("limit", 50)
                if not isinstance(limit, int) or not 1 <= limit <= 100:
                    errors.append(f"{label}.limit must be an integer from 1 to 100")
        jira_writes = jira.get("writes") or {}
        if jira_writes.get("enabled"):
            if not permissions.get("jira_writes_enabled", False):
                errors.append(
                    "permissions.jira_writes_enabled must be true when Jira lifecycle writes are enabled"
                )
            if jira_writes.get("duplicate_check") is not True:
                errors.append("modules.jira-sweep.writes.duplicate_check must be true")
            allowed_operations = jira_writes.get("allowed_operations")
            supported_operations = {"create", "update", "comment", "transition"}
            if (
                not isinstance(allowed_operations, list)
                or not allowed_operations
                or any(operation not in supported_operations for operation in allowed_operations)
            ):
                errors.append(
                    "modules.jira-sweep.writes.allowed_operations must contain supported Jira operations"
                )
            write_scopes = jira_writes.get("scope_ids")
            if not isinstance(write_scopes, list) or not write_scopes:
                errors.append("modules.jira-sweep.writes.scope_ids must be a non-empty array")
                write_scopes = []
            unknown_write_scopes = sorted(set(write_scopes) - seen)
            if unknown_write_scopes:
                errors.append(
                    "modules.jira-sweep.writes.scope_ids contains unknown scopes: "
                    + ", ".join(unknown_write_scopes)
                )
            projects = jira_writes.get("projects")
            if not isinstance(projects, dict):
                errors.append("modules.jira-sweep.writes.projects must be an object")
                projects = {}
            for scope_id in write_scopes:
                project = projects.get(scope_id) or {}
                if not _nonempty_string(project.get("project_key")):
                    errors.append(
                        f"modules.jira-sweep.writes.projects.{scope_id}.project_key must be a non-empty string"
                    )
                if not _nonempty_string(project.get("issue_type")):
                    errors.append(
                        f"modules.jira-sweep.writes.projects.{scope_id}.issue_type must be a non-empty string"
                    )

    action_routing = modules.get("action-routing") or {}
    if action_routing.get("enabled"):
        if action_routing.get("overlap_policy") != "primary_with_links":
            errors.append("modules.action-routing.overlap_policy must be primary_with_links")
        if action_routing.get("unready_policy") != "pause_and_ask":
            errors.append("modules.action-routing.unready_policy must be pause_and_ask")
        destinations = action_routing.get("destinations")
        if not isinstance(destinations, dict) or not destinations:
            errors.append("modules.action-routing.destinations must be a non-empty object")
        else:
            unknown_destinations = sorted(set(destinations) - {"gtd", "jira", "crm"})
            if unknown_destinations:
                errors.append(
                    "modules.action-routing.destinations has unsupported keys: "
                    + ", ".join(unknown_destinations)
                )
            for destination, module_id in destinations.items():
                if not _nonempty_string(module_id):
                    errors.append(
                        f"modules.action-routing.destinations.{destination} must name a module"
                    )
                elif not (modules.get(module_id) or {}).get("enabled"):
                    errors.append(
                        f"modules.action-routing destination {destination} references a disabled module: {module_id}"
                    )
        rules = action_routing.get("rules") or {}
        if not isinstance(rules, dict):
            errors.append("modules.action-routing.rules must be an object")
        else:
            allowed_rule_destinations = set(destinations or {}) | {"drop"}
            for action_kind, destination in rules.items():
                if not _nonempty_string(action_kind) or destination not in allowed_rule_destinations:
                    errors.append(
                        f"modules.action-routing.rules.{action_kind} must reference a configured destination or drop"
                    )

    gtd = modules.get("gtd-google-sheet") or {}
    if gtd.get("enabled"):
        if not isinstance(gtd.get("connector_configured"), bool):
            errors.append("modules.gtd-google-sheet.connector_configured must be a boolean")
        if not _nonempty_string(gtd.get("spreadsheet_id")) and not _nonempty_string(
            gtd.get("spreadsheet_url")
        ):
            errors.append("modules.gtd-google-sheet requires spreadsheet_id or spreadsheet_url")
        gtd_scopes = gtd.get("scope_ids")
        if not isinstance(gtd_scopes, list) or not gtd_scopes:
            errors.append("modules.gtd-google-sheet.scope_ids must be a non-empty array")
            gtd_scopes = []
        unknown_gtd_scopes = sorted(set(gtd_scopes) - seen)
        if unknown_gtd_scopes:
            errors.append(
                "modules.gtd-google-sheet.scope_ids contains unknown scopes: "
                + ", ".join(unknown_gtd_scopes)
            )
        area_values = gtd.get("area_values")
        if not isinstance(area_values, dict):
            errors.append("modules.gtd-google-sheet.area_values must be an object")
            area_values = {}
        for scope_id in gtd_scopes:
            if not _nonempty_string(area_values.get(scope_id)):
                errors.append(
                    f"modules.gtd-google-sheet.area_values.{scope_id} must be a non-empty string"
                )
        tab_map = gtd.get("tab_map")
        if not isinstance(tab_map, dict):
            errors.append("modules.gtd-google-sheet.tab_map must be an object")
            tab_map = {}
        for key in ("next_actions", "waiting_fors", "inbox", "archive"):
            if not _nonempty_string(tab_map.get(key)):
                errors.append(f"modules.gtd-google-sheet.tab_map.{key} must be a non-empty string")
        if gtd.get("archive_before_clear") is not True:
            errors.append("modules.gtd-google-sheet.archive_before_clear must be true")
        if not isinstance(gtd.get("allow_writes", False), bool):
            errors.append("modules.gtd-google-sheet.allow_writes must be a boolean")
        elif gtd.get("allow_writes") and not permissions.get("gtd_writes_enabled", False):
            errors.append(
                "permissions.gtd_writes_enabled must be true when GTD live writes are enabled"
            )

    local_files = modules.get("local-files") or {}
    if local_files.get("enabled"):
        max_files = local_files.get("max_files", 200)
        if not isinstance(max_files, int) or not 1 <= max_files <= 5000:
            errors.append("modules.local-files.max_files must be an integer from 1 to 5000")
        max_scanned_files = local_files.get("max_scanned_files", 5000)
        if not isinstance(max_scanned_files, int) or not 1 <= max_scanned_files <= 100000:
            errors.append("modules.local-files.max_scanned_files must be an integer from 1 to 100000")
        max_scanned_directories = local_files.get("max_scanned_directories", 1000)
        if not isinstance(max_scanned_directories, int) or not 1 <= max_scanned_directories <= 10000:
            errors.append("modules.local-files.max_scanned_directories must be an integer from 1 to 10000")
        max_scan_seconds = local_files.get("max_scan_seconds", 15)
        if not isinstance(max_scan_seconds, int) or not 1 <= max_scan_seconds <= 300:
            errors.append("modules.local-files.max_scan_seconds must be an integer from 1 to 300")
        roots = local_files.get("roots")
        if not isinstance(roots, list) or not roots:
            errors.append("modules.local-files.roots must be a non-empty array")
        else:
            for index, root_config in enumerate(roots):
                label = f"modules.local-files.roots[{index}]"
                if not isinstance(root_config, dict):
                    errors.append(f"{label} must be an object")
                    continue
                path_text = root_config.get("path")
                if not _nonempty_string(path_text):
                    errors.append(f"{label}.path must be a non-empty string")
                else:
                    root_path = Path(path_text).expanduser()
                    if strict_paths and not root_path.is_dir():
                        errors.append(f"{label}.path does not exist or is not a directory: {root_path}")
                    elif not root_path.is_dir():
                        warnings.append(f"{label}.path does not exist or is not a directory: {root_path}")
                if root_config.get("scope_id") not in seen:
                    errors.append(f"{label}.scope_id must reference a configured scope")
                if not isinstance(root_config.get("recursive", True), bool):
                    errors.append(f"{label}.recursive must be a boolean")
                lookback = root_config.get("lookback_days", 7)
                if not isinstance(lookback, int) or not 1 <= lookback <= 365:
                    errors.append(f"{label}.lookback_days must be an integer from 1 to 365")
                extensions = root_config.get("include_extensions", [])
                if not isinstance(extensions, list) or any(
                    not _nonempty_string(extension) for extension in extensions
                ):
                    errors.append(f"{label}.include_extensions must be an array of non-empty strings")

    crm = modules.get("crm-google-sheet") or {}
    if crm.get("enabled"):
        crm_mode = crm.get("mode", "portable_workbook")
        if crm_mode not in {"portable_workbook", "delegated_handler"}:
            errors.append(
                "modules.crm-google-sheet.mode must be portable_workbook or delegated_handler"
            )
        if not isinstance(crm.get("allow_live_sheet_writes", False), bool):
            errors.append("modules.crm-google-sheet.allow_live_sheet_writes must be a boolean")
        if crm_mode == "portable_workbook":
            if not _nonempty_string(crm.get("workbook_path")):
                errors.append("modules.crm-google-sheet.workbook_path must be a non-empty string")
            if not _nonempty_string(crm.get("proposal_output_dir")):
                errors.append(
                    "modules.crm-google-sheet.proposal_output_dir must be a non-empty string"
                )
        elif crm_mode == "delegated_handler":
            scope_ids = crm.get("scope_ids")
            if not isinstance(scope_ids, list) or not scope_ids:
                errors.append("modules.crm-google-sheet.scope_ids must be a non-empty array")
            elif any(not _nonempty_string(scope_id) for scope_id in scope_ids):
                errors.append(
                    "modules.crm-google-sheet.scope_ids must contain non-empty strings"
                )
            else:
                unknown_scopes = sorted(set(scope_ids) - seen)
                if unknown_scopes:
                    errors.append(
                        "modules.crm-google-sheet.scope_ids contains unknown scopes: "
                        + ", ".join(unknown_scopes)
                    )
            if not _nonempty_string(crm.get("handler_skill")):
                errors.append("modules.crm-google-sheet.handler_skill must be a non-empty string")
            if "handler_path" in crm and not _nonempty_string(crm.get("handler_path")):
                errors.append("modules.crm-google-sheet.handler_path must be a non-empty string")
            if crm.get("review_mode") != "incremental_daily":
                errors.append(
                    "modules.crm-google-sheet.review_mode must be incremental_daily"
                )
            first_days = crm.get("first_run_lookback_days", 14)
            if not isinstance(first_days, int) or not 1 <= first_days <= 365:
                errors.append(
                    "modules.crm-google-sheet.first_run_lookback_days must be an integer from 1 to 365"
                )
            overlap_hours = crm.get("overlap_hours", 24)
            if not isinstance(overlap_hours, int) or not 0 <= overlap_hours <= 168:
                errors.append(
                    "modules.crm-google-sheet.overlap_hours must be an integer from 0 to 168"
                )
            if not isinstance(crm.get("allow_new_rows", False), bool):
                errors.append("modules.crm-google-sheet.allow_new_rows must be a boolean")
            if crm.get("minimum_confidence", "high") not in {"medium", "high"}:
                errors.append(
                    "modules.crm-google-sheet.minimum_confidence must be medium or high"
                )
            if not isinstance(crm.get("roll_weekly_jira", False), bool):
                errors.append("modules.crm-google-sheet.roll_weekly_jira must be a boolean")
            elif crm.get("roll_weekly_jira", False):
                errors.append(
                    "modules.crm-google-sheet.roll_weekly_jira must be false for incremental_daily"
                )
            if crm.get("allow_live_sheet_writes", False) and not permissions.get(
                "crm_writes_enabled", False
            ):
                errors.append(
                    "permissions.crm_writes_enabled must be true when delegated CRM live writes are enabled"
                )

    email_delivery = modules.get("email-delivery") or {}
    if email_delivery.get("enabled"):
        if email_delivery.get("provider") != "gmail":
            errors.append("modules.email-delivery.provider must be gmail")
        if email_delivery.get("connector") != "gmail":
            errors.append("modules.email-delivery.connector must be gmail")
        if not isinstance(email_delivery.get("connector_configured"), bool):
            errors.append("modules.email-delivery.connector_configured must be a boolean")
        sender = email_delivery.get("from")
        if not _nonempty_string(sender) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", sender):
            errors.append("modules.email-delivery.from must be an email address")
        recipients = email_delivery.get("recipients")
        if not isinstance(recipients, list) or not recipients:
            errors.append("modules.email-delivery.recipients must be a non-empty array")
        elif any(
            not _nonempty_string(recipient)
            or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", recipient)
            for recipient in recipients
        ):
            errors.append("modules.email-delivery.recipients must contain email addresses")
        if email_delivery.get("mode") not in {
            "send_after_approved_close",
            "draft_after_approved_close",
        }:
            errors.append(
                "modules.email-delivery.mode must be send_after_approved_close or "
                "draft_after_approved_close"
            )
        if not _nonempty_string(email_delivery.get("subject_template")):
            errors.append("modules.email-delivery.subject_template must be a non-empty string")
        if email_delivery.get("body_style") not in {"summary", "full_plan"}:
            errors.append("modules.email-delivery.body_style must be summary or full_plan")
        attachments = email_delivery.get("attachments")
        if not isinstance(attachments, list) or any(
            attachment not in {"daily_plan_docx"} for attachment in attachments
        ):
            errors.append("modules.email-delivery.attachments may contain only daily_plan_docx")
        artifact_exports = (
            (artifacts.get("exports") or {}) if isinstance(artifacts, dict) else {}
        )
        if "daily_plan_docx" in (attachments or []) and not export_enabled(
            artifact_exports, "daily_plan_docx"
        ):
            errors.append("email delivery of daily_plan_docx requires that export to be enabled")
        if not permissions.get("email_delivery_enabled", False):
            errors.append(
                "permissions.email_delivery_enabled must be true when email-delivery is enabled"
            )

    takeaway = ((profile.get("features") or {}).get("daily_takeaways") or {})
    if not isinstance(takeaway.get("enabled", False), bool):
        errors.append("features.daily_takeaways.enabled must be a boolean")
    max_items = takeaway.get("max_items", 3)
    if not isinstance(max_items, int) or not 1 <= max_items <= 3:
        errors.append("features.daily_takeaways.max_items must be an integer from 1 to 3")
    required_items = takeaway.get("required_items", 0)
    if not isinstance(required_items, int) or not 0 <= required_items <= 3:
        errors.append("features.daily_takeaways.required_items must be an integer from 0 to 3")
    elif isinstance(max_items, int) and required_items > max_items:
        errors.append("features.daily_takeaways.required_items cannot exceed max_items")
    if takeaway.get("incomplete_policy", "allow_partial") not in {
        "allow_partial",
        "ask_until_complete",
    }:
        errors.append(
            "features.daily_takeaways.incomplete_policy must be allow_partial or ask_until_complete"
        )
    recap = ((profile.get("features") or {}).get("recurring_meeting_recap") or {})
    if not isinstance(recap.get("enabled", False), bool):
        errors.append("features.recurring_meeting_recap.enabled must be a boolean")
    if not isinstance((profile.get("features") or {}).get("docx_page_numbers", False), bool):
        errors.append("features.docx_page_numbers must be a boolean")

    outreach = ((profile.get("features") or {}).get("people_outreach") or {})
    if not isinstance(outreach, dict):
        errors.append("features.people_outreach must be an object")
    elif outreach.get("enabled", False):
        if not _nonempty_string(outreach.get("list_path")):
            errors.append("features.people_outreach.list_path must be a non-empty string")
        if not _nonempty_string(outreach.get("state_path")):
            errors.append("features.people_outreach.state_path must be a non-empty string")
        count = outreach.get("daily_count", 2)
        if not isinstance(count, int) or count < 1:
            errors.append("features.people_outreach.daily_count must be a positive integer")
        if outreach.get("schedule", "workdays_and_manual_runs") != "workdays_and_manual_runs":
            errors.append("features.people_outreach.schedule must be workdays_and_manual_runs")
        if outreach.get("selection_policy", "round_robin") != "round_robin":
            errors.append("features.people_outreach.selection_policy must be round_robin")
        if outreach.get("duplicate_policy", "count_entries") != "count_entries":
            errors.append("features.people_outreach.duplicate_policy must be count_entries")

    return errors, warnings


def _values(item: dict) -> list[str]:
    values: list[str] = []
    for key in ("title", "subject", "text", "body", "snippet", "project", "account"):
        value = item.get(key)
        if isinstance(value, str):
            values.append(value)
    participants = item.get("participants") or []
    if isinstance(participants, list):
        values.extend(str(value) for value in participants)
    source = item.get("source") or {}
    if isinstance(source, dict):
        values.extend(str(value) for value in source.values() if value is not None)
    return values


def _matches_term(text: str, term: str) -> bool:
    escaped = re.escape(term.strip())
    if not escaped:
        return False
    return bool(re.search(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", text, flags=re.IGNORECASE))


def _matches_any(values: Iterable[str], terms: Iterable[str]) -> bool:
    material = "\n".join(values)
    return any(_matches_term(material, term) for term in terms)


def classify_item(item: dict, profile: dict) -> dict:
    """Return a deterministic classification result for normalized evidence."""
    values = _values(item)
    for exclusion in (profile.get("routing") or {}).get("global_exclusions") or []:
        terms = exclusion.get("match_terms") or [exclusion.get("name")]
        if _matches_any(values, [term for term in terms if term]):
            return {"status": "excluded", "reason": exclusion.get("name"), "item": item}

    scopes = profile.get("scopes") or []

    def assign(scope: dict, method: str) -> dict:
        if _matches_any(values, scope.get("exclude_terms") or []):
            return {"status": "excluded", "reason": f"{scope['id']}:scope_exclusion", "item": item}
        return {"status": "classified", "scope_id": scope["id"], "method": method, "item": item}

    explicit = item.get("scope_id")
    explicit_scope = next((scope for scope in scopes if scope.get("id") == explicit), None)
    if explicit_scope:
        return assign(explicit_scope, "explicit")

    source = item.get("source") or {}
    provider_scope_ids: set[str] = set()
    if isinstance(source, dict):
        for module_id in ("mail-sweep", "calendar-sweep"):
            for provider in (((profile.get("modules") or {}).get(module_id) or {}).get("providers") or []):
                if provider.get("provider") != source.get("provider"):
                    continue
                configured_account = provider.get("account")
                if configured_account and str(configured_account).casefold() != str(source.get("account") or "").casefold():
                    continue
                provider_scope_ids.update(provider.get("scope_ids") or [])
    if len(provider_scope_ids) == 1:
        selected = next((scope for scope in scopes if scope.get("id") in provider_scope_ids), None)
        if selected:
            return assign(selected, "provider_binding")

    source_values = [str(value) for value in source.values()] if isinstance(source, dict) else []
    binding_matches = [
        scope for scope in scopes if _matches_any(source_values, scope.get("source_bindings") or [])
    ]
    if len(binding_matches) == 1:
        return assign(binding_matches[0], "source_binding")

    domain_matches: list[dict] = []
    for scope in scopes:
        if any(domain.lower() in "\n".join(values).lower() for domain in scope.get("domains") or []):
            domain_matches.append(scope)
    if len(domain_matches) == 1:
        return assign(domain_matches[0], "domain")

    term_matches: list[dict] = []
    for scope in scopes:
        terms = (scope.get("aliases") or []) + (scope.get("include_terms") or [])
        if _matches_any(values, terms):
            term_matches.append(scope)
    if len(term_matches) == 1:
        return assign(term_matches[0], "term")

    if len(scopes) == 1:
        return assign(scopes[0], "single_scope")

    reason = "ambiguous" if binding_matches or domain_matches or term_matches else "no_match"
    return {"status": "unclassified", "reason": reason, "item": item}


def classify_items(items: Iterable[dict], profile: dict) -> dict:
    result = {"classified": [], "excluded": [], "unclassified": []}
    for item in items:
        classified = classify_item(item, profile)
        result[classified["status"]].append(classified)
    result["requires_resolution"] = bool(result["unclassified"])
    return result


def migrate_v1_profile(legacy: dict, profile_id: str | None = None, workspace_root: str | None = None) -> dict:
    owner = legacy.get("owner") or {}
    name = owner.get("name") or "Migrated User"
    selected_id = slugify(profile_id or legacy.get("profile_name") or f"{name}-close")
    old_paths = legacy.get("paths") or {}
    inferred_root = workspace_root or old_paths.get("daily_plan_dir")
    if inferred_root:
        inferred = Path(inferred_root).expanduser()
        if inferred.name.lower() in {"daily plan", "plans"}:
            inferred = inferred.parent
    else:
        inferred = Path.home() / "Documents" / "close-day"

    overrides = {}
    mapping = {
        "daily_plan_dir": "plans",
        "agenda_dir": "agendas",
        "eod_log_dir": "logs",
    }
    for old_key, new_key in mapping.items():
        if old_paths.get(old_key):
            overrides[new_key] = old_paths[old_key]

    exclusions = ((legacy.get("scope_exclusions") or {}).get("topics") or [])
    enabled_legacy = legacy.get("enabled_modules") or []
    enabled: list[str] = ["task-store", "daily-artifacts"]
    if any(item in enabled_legacy for item in ("gmail-sweep", "sent-mail-outlook")):
        enabled.append("mail-sweep")
    if "calendar-outlook" in enabled_legacy:
        enabled.append("calendar-sweep")
    for item in ("granola-meetings", "slack-sweep", "teams-local-cache", "source-of-truth", "crm-google-sheet"):
        if item in enabled_legacy:
            enabled.append(item)

    mail_providers = []
    if "gmail-sweep" in enabled_legacy:
        gmail = (legacy.get("modules") or {}).get("gmail-sweep") or {}
        mail_providers.append({
            "provider": "gmail",
            "account": gmail.get("account") or owner.get("primary_email"),
            "connector": "gmail",
            "scope_ids": ["primary"],
        })
    if "sent-mail-outlook" in enabled_legacy:
        mail_providers.append({"provider": "outlook", "adapter": "outlook-com", "scope_ids": ["primary"]})

    calendar_providers = []
    if "calendar-outlook" in enabled_legacy:
        calendar_providers.append({"provider": "outlook", "adapter": "outlook-com", "scope_ids": ["primary"]})

    write_mode = legacy.get("write_mode") or {}
    document_enabled = bool(write_mode.get("document_generation_enabled"))
    migrated = {
        "schema_version": SCHEMA_VERSION,
        "profile": {"id": selected_id, "name": legacy.get("profile_name") or f"{name} Close"},
        "owner": {
            "name": name,
            "primary_email": owner.get("primary_email"),
            "timezone": owner.get("timezone") or "UTC",
        },
        "schedule": {
            "workdays": owner.get("workdays") or ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "close_out_time": owner.get("close_out_time") or "17:00",
        },
        "scopes": [{
            "id": "primary",
            "type": "organization",
            "name": "Primary",
            "aliases": [],
            "domains": [],
            "include_terms": [],
            "exclude_terms": [],
            "source_bindings": [],
        }],
        "routing": {"unclassified_policy": "pause_and_ask", "global_exclusions": exclusions},
        "artifacts": {
            "workspace_root": str(inferred),
            "path_overrides": overrides,
            "canonical": {"markdown": True, "json": True},
            "exports": {"docx": document_enabled, "xlsx": bool(old_paths.get("gtd_workbook"))},
        },
        "features": {
            "daily_takeaways": {
                "enabled": True,
                "max_items": 3,
                "required_items": 0,
                "incomplete_policy": "allow_partial",
            },
            "recurring_meeting_recap": {"enabled": True},
            "docx_page_numbers": True,
        },
        "privacy": legacy.get("privacy") or {"allow_raw_external_content": False},
        "permissions": {
            "proposal_required": True,
            "external_writes_enabled": bool(write_mode.get("external_writes_enabled")),
            "local_artifact_writes_enabled": document_enabled,
            "jira_ticket_approval_required": True,
            "jira_writes_enabled": False,
            "gtd_writes_enabled": False,
            "crm_writes_enabled": bool(write_mode.get("crm_writes_enabled")),
            "email_delivery_enabled": False,
        },
        "enabled_modules": list(dict.fromkeys(enabled)),
        "modules": {
            "mail-sweep": {"enabled": "mail-sweep" in enabled, "providers": mail_providers},
            "calendar-sweep": {"enabled": "calendar-sweep" in enabled, "providers": calendar_providers, "days_ahead": 1},
            "task-store": {
                "enabled": True,
                "provider": "xlsx" if old_paths.get("gtd_workbook") else "portable",
                "existing_path": old_paths.get("gtd_workbook"),
                "allow_writes": bool(((legacy.get("modules") or {}).get("gtd-workbook") or {}).get("allow_writes")),
            },
            "daily-artifacts": {"enabled": True},
            **{
                module_id: {**(((legacy.get("modules") or {}).get(module_id)) or {}), "enabled": True}
                for module_id in enabled
                if module_id not in {"mail-sweep", "calendar-sweep", "task-store", "daily-artifacts"}
            },
        },
    }
    crm_module = migrated["modules"].get("crm-google-sheet")
    if crm_module:
        crm_module.setdefault("mode", "portable_workbook")
        legacy_crm = legacy.get("crm") or {}
        crm_module.setdefault(
            "workbook_path",
            legacy_crm.get("workbook_path") or str(inferred / "CRM" / "close-day-crm.xlsx"),
        )
        crm_module.setdefault(
            "csv_seed_dir",
            legacy_crm.get("csv_seed_dir") or str(inferred / "CRM" / "csv_seed"),
        )
        crm_module.setdefault(
            "proposal_output_dir",
            legacy_crm.get("proposal_output_dir") or str(inferred / "CRM" / "proposals"),
        )
        crm_module.setdefault("allow_live_sheet_writes", False)
    source_module = migrated["modules"].get("source-of-truth")
    if source_module:
        source_module.setdefault("mode", "confluence")
        source_module.setdefault(
            "mapping_path", str(inferred / "Source of Truth" / "source-of-truth-map.csv")
        )
    return migrated
