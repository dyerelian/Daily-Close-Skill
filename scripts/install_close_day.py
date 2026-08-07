#!/usr/bin/env python3
"""Cross-platform installer and environment check for the close-day skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from close_day_config import default_config_root


ROOT = Path(__file__).resolve().parents[1]


def copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if name in {".git", "outputs", "__pycache__", ".pytest_cache"}:
            ignored.add(name)
        if name in {"daily-close.local.json", "onboarding.answers.local.json", "registry.local.json"}:
            ignored.add(name)
        if name.endswith(".local.json"):
            ignored.add(name)
    return ignored


def default_skill_target() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    return base / "skills" / "close-day"


def environment_report(target: Path | None = None) -> dict:
    selected = target or default_skill_target()
    dependencies = {"openpyxl": importlib.util.find_spec("openpyxl") is not None}
    return {
        "python": platform.python_version(),
        "python_supported": sys.version_info >= (3, 10),
        "platform": platform.platform(),
        "source": str(ROOT),
        "target": str(selected),
        "target_exists": selected.exists() or selected.is_symlink(),
        "config_root": str(default_config_root()),
        "optional_dependencies": dependencies,
        "ready": sys.version_info >= (3, 10),
    }


def same_location(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def is_linklike(path: Path) -> bool:
    if path.is_symlink():
        return True
    if platform.system() != "Windows":
        return False
    try:
        return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (AttributeError, OSError):
        return False


def make_link(source: Path, target: Path) -> str:
    try:
        target.symlink_to(source, target_is_directory=True)
        return "symlink"
    except OSError:
        if platform.system() != "Windows":
            raise
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(target), str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise OSError(result.stderr.strip() or result.stdout.strip() or "junction creation failed")
    return "junction"


def install(source: Path, target: Path, mode: str, force: bool, dry_run: bool) -> dict:
    if target.exists() or target.is_symlink():
        if same_location(source, target):
            return {"status": "already_installed", "mode": "existing", "target": str(target)}
        if not force:
            raise FileExistsError(f"target already exists: {target}; use --force to replace it")
        private_candidates = [
            target / "config" / "daily-close.local.json",
            target / "config" / "onboarding.answers.local.json",
        ]
        if any(path.exists() for path in private_candidates):
            raise ValueError(
                "refusing to replace an installation containing private legacy config; "
                "migrate or back it up first"
            )
        resolved = target.resolve()
        forbidden = {Path(resolved.anchor), Path.home().resolve(), source.resolve(), source.parent.resolve()}
        if resolved in forbidden or not target.name:
            raise ValueError(f"refusing to replace unsafe target: {resolved}")
        if not dry_run:
            if target.is_file():
                target.unlink()
            elif is_linklike(target):
                target.rmdir()
            else:
                shutil.rmtree(target)
    if dry_run:
        return {"status": "dry_run", "mode": mode, "source": str(source), "target": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    selected_mode = mode
    if mode in {"auto", "link"}:
        try:
            selected_mode = make_link(source, target)
        except OSError:
            if mode == "link":
                raise
            shutil.copytree(source, target, ignore=copy_ignore)
            selected_mode = "copy"
    else:
        shutil.copytree(source, target, ignore=copy_ignore)
        selected_mode = "copy"
    return {"status": "installed", "mode": selected_mode, "source": str(source), "target": str(target)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check or install the close-day Codex skill.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="Check runtime, target, and optional dependencies.")
    check.add_argument("--target")
    install_parser = sub.add_parser("install", help="Install/link the skill and begin onboarding.")
    install_parser.add_argument("--source", default=str(ROOT))
    install_parser.add_argument("--target")
    install_parser.add_argument("--mode", choices=("auto", "link", "copy"), default="auto")
    install_parser.add_argument("--force", action="store_true")
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.add_argument("--skip-onboarding", action="store_true")
    args = parser.parse_args()

    target = Path(args.target).expanduser() if getattr(args, "target", None) else default_skill_target()
    if args.command == "check":
        report = environment_report(target)
        print(json.dumps(report, indent=2))
        return 0 if report["ready"] else 1

    source = Path(args.source).expanduser().resolve()
    report = environment_report(target)
    if not report["python_supported"]:
        print(json.dumps(report, indent=2))
        return 1
    result = install(source, target, args.mode, args.force, args.dry_run)
    result["onboarding_command"] = f'{sys.executable} "{target / "scripts" / "onboard_close_day.py"}" run --make-default'
    print(json.dumps(result, indent=2))
    if args.dry_run or args.skip_onboarding:
        return 0
    onboarding = target / "scripts" / "onboard_close_day.py"
    return subprocess.run([sys.executable, str(onboarding), "run", "--make-default"], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
