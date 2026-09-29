#!/usr/bin/env python3
"""Offline protocol installer. Preview by default; existing files are never overwritten."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys

VERSION = "4.0.0"
BUNDLE = Path(__file__).absolute().parent.parent
MANIFEST = "ai/protocol-manifest.json"
PROFILES = ("universal", "website", "webapp", "api", "bot", "automation")
MODES = ("solo", "team", "strict")
REQUIRED = {
    "AGENTS.md", "CLAUDE.md", "ai/README.md", "ai/ROLES.md", "ai/PROMPTS.md",
    "ai/projects/_TEMPLATE.md", "tools/ai_protocol.py", MANIFEST,
    *(f"ai/templates/{name}.md" for name in ("TASK", "REVIEW", "HANDOFF", "STATE", "DECISION", "RELEASE")),
    *(f"ai/playbooks/{name}.md" for name in PROFILES),
}
GENERATED = {"ai/PROJECT.md", "ai/STATE.md", "ai/protocol.json"}
ONBOARDING_FIELDS = (
    "Owner/business decision maker", "Verified on / revision", "Purpose and users",
    "Current milestone", "Stack / runtime versions", "Entry points / module map",
    "install", "dev", "test", "lint", "typecheck", "build",
)


class ProtocolError(Exception):
    """Expected validation or installation failure."""


def no_links(path: Path) -> None:
    # Inspect before resolve(): resolving first would hide junctions/symlinks.
    # Cloud placeholder reparse points are not directory redirections.
    for item in reversed((path, *path.parents)):
        if os.path.lexists(item):
            info = item.lstat()
            if item.is_symlink() or getattr(info, "st_reparse_tag", 0) in (0xA0000003, 0xA000000C):
                raise ProtocolError(f"Linked path is not supported: {item}")


def root_path(value: str | Path) -> Path:
    path = Path(os.path.abspath(Path(value).expanduser()))
    no_links(path)
    if path.exists() and not path.is_dir():
        raise ProtocolError(f"Expected a directory: {path}")
    return path


def relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError("Manifest paths must be nonempty strings")
    parts = value.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if (PurePosixPath(value).is_absolute() or any(
        part in ("", ".", "..") or part != part.rstrip(" .")
        or any(ord(char) < 32 or char in '\\:<>"|?*' for char in part)
        or part.split(".")[0].upper() in reserved for part in parts
    )):
        raise ProtocolError(f"Unsafe manifest path: {value!r}")
    return value


def at(root: Path, relative: str) -> Path:
    path = root.joinpath(*relative_path(relative).split("/"))
    no_links(path)
    for parent in path.parents:
        if parent == root.parent:
            break
        if parent.exists() and not parent.is_dir():
            raise ProtocolError(f"Parent is not a directory: {parent}")
    return path


def read_text(path: Path) -> str:
    if not path.is_file():
        raise ProtocolError(f"Required file missing: {path}")
    content = path.read_text(encoding="utf-8-sig")
    if not content.strip():
        raise ProtocolError(f"Required file is empty: {path}")
    return content


def read_json(path: Path) -> dict:
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(data, dict):
        raise ProtocolError(f"Expected a JSON object: {path}")
    return data


def manifest(root: Path) -> list[str]:
    data = read_json(at(root, MANIFEST))
    if data.get("version") != VERSION or not isinstance(data.get("files"), list):
        raise ProtocolError(f"Manifest must have version {VERSION} and a files list")
    paths = [relative_path(value) for value in data["files"]]
    if len({path.casefold() for path in paths}) != len(paths):
        raise ProtocolError("Duplicate or case-colliding manifest paths")
    # This is a deliberately closed public payload: no local tasks, facts, or secrets.
    if set(paths) != REQUIRED:
        missing, extra = sorted(REQUIRED - set(paths)), sorted(set(paths) - REQUIRED)
        raise ProtocolError(f"Unexpected public manifest: missing={missing}, extra={extra}")
    for relative in paths:
        read_text(at(root, relative))
    return paths


def project_name(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 120 or any(ord(c) < 32 or c in "{}" for c in value):
        raise ProtocolError("Project name must be 1-120 characters with no control characters or braces")
    return value


def render(template: str, name: str, profile: str, mode: str) -> bytes:
    for key, value in {"PROJECT_NAME": name, "PROJECT_TYPE": profile, "WORK_MODE": mode}.items():
        template = template.replace("{{" + key + "}}", value)
    if re.search(r"\{\{[A-Z_]+\}\}", template):
        raise ProtocolError("Unresolved template variable")
    return template.encode("utf-8")


def install(source: Path, target: Path, name: str, profile: str, mode: str, apply: bool = False) -> None:
    source, target = root_path(source), root_path(target)
    if source == target or source in target.parents or target in source.parents:
        raise ProtocolError("Source and target must not contain one another")
    name = project_name(name)
    if profile not in PROFILES or mode not in MODES:
        raise ProtocolError("Unsupported profile or mode")
    if not target.parent.is_dir():
        raise ProtocolError(f"Create the target's parent directory first: {target.parent}")
    payload = {relative: at(source, relative).read_bytes() for relative in manifest(source)}
    payload["ai/PROJECT.md"] = render(read_text(at(source, "ai/projects/_TEMPLATE.md")), name, profile, mode)
    payload["ai/STATE.md"] = render(read_text(at(source, "ai/templates/STATE.md")), name, profile, mode)
    payload["ai/protocol.json"] = (json.dumps({
        "version": VERSION, "project_name": name, "project_type": profile, "mode": mode,
    }, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    pending: list[tuple[Path, bytes]] = []
    conflicts: list[str] = []
    for relative, content in sorted(payload.items()):
        dest = at(target, relative)
        if dest.exists():
            if dest.is_file() and dest.read_bytes() == content:
                print(f"KEEP     {relative}")
            else:
                conflicts.append(relative)
        else:
            pending.append((dest, content))
            print(f"CREATE   {relative}")
    if conflicts:
        raise ProtocolError("No files written. Conflicts: " + ", ".join(conflicts)
                            + ". Install into an empty folder and merge manually; see ai/README.md.")
    if not apply:
        print(f"PREVIEW: {len(pending)} new files. No writes. Add --apply to install.")
        return

    created_files: list[Path] = []
    created_dirs: list[Path] = []

    def make_directory(directory: Path) -> None:
        if directory.is_dir():
            return
        if directory != target and target not in directory.parents:
            raise ProtocolError(f"Refusing to create outside target: {directory}")
        make_directory(directory.parent)
        directory.mkdir()
        created_dirs.append(directory)

    try:
        for dest, content in pending:
            no_links(dest)
            make_directory(dest.parent)
            # Exclusive creation also prevents overwriting files created after preflight.
            with dest.open("xb") as handle:
                created_files.append(dest)
                handle.write(content)
    except (OSError, ProtocolError) as exc:
        rollback_errors: list[str] = []
        for path in reversed(created_files):
            try:
                no_links(path)
                path.unlink()
            except OSError as cleanup_exc:
                rollback_errors.append(f"{path}: {cleanup_exc}")
            except ProtocolError as cleanup_exc:
                rollback_errors.append(str(cleanup_exc))
        for directory in reversed(created_dirs):
            try:
                no_links(directory)
                directory.rmdir()  # Empty directories only; never recursive deletion.
            except (OSError, ProtocolError) as cleanup_exc:
                rollback_errors.append(f"{directory}: {cleanup_exc}")
        detail = "; rollback needs inspection: " + "; ".join(rollback_errors) if rollback_errors else "; new files rolled back"
        raise ProtocolError(f"Installation failed: {exc}{detail}") from exc
    print(f"INSTALLED: {len(pending)} new files in {target}")
    print("Next: fill ai/PROJECT.md from actual repository facts; run check.")


def check(root: Path, strict: bool = False) -> None:
    root = root_path(root)
    manifest(root)
    config = read_json(at(root, "ai/protocol.json"))
    if (config.get("version") != VERSION or config.get("mode") not in MODES
            or config.get("project_type") not in PROFILES or not isinstance(config.get("project_name"), str)):
        raise ProtocolError("Invalid protocol config: version, mode, project_type or project_name")
    project_name(config["project_name"])
    profile = read_text(at(root, "ai/PROJECT.md"))
    state = read_text(at(root, "ai/STATE.md"))
    if re.search(r"\{\{[A-Z_]+\}\}", profile + state):
        raise ProtocolError("Unresolved template variables in project profile/state")
    for heading in ("Identity", "Architecture", "Commands", "Business rules and security"):
        if f"## {heading}" not in profile.splitlines():
            raise ProtocolError(f"Project profile missing heading: {heading}")
    for label, expected in (("Project type", config["project_type"]), ("Work mode", config["mode"])):
        values = re.findall(r"^- " + re.escape(label) + r":\s*(.*)$", profile, re.MULTILINE)
        if values != [expected]:
            raise ProtocolError(f"Project profile {label} disagrees with ai/protocol.json")
    missing = []
    for label in ONBOARDING_FIELDS:
        values = re.findall(r"^- " + re.escape(label) + r":[ \t]*(.*)$", profile, re.MULTILINE)
        value = values[0].strip() if len(values) == 1 else ""
        if (not value or re.search(r"\b(UNKNOWN|TODO|TBD)\b|<[^>]+>", value, re.IGNORECASE)
                or (value.upper().startswith("N/A") and len(value[3:].strip(" -—:")) < 3)):
            missing.append(label)
    if missing:
        message = "Setup fields need verified facts (or N/A with reason): " + ", ".join(missing)
        if strict:
            raise ProtocolError(message)
        print("SETUP PENDING: " + message)
    print(f"PASS: protocol structure ({config['mode']}, {config['project_type']}). Application behavior not checked.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("bundle", help="Validate the public source bundle")
    install_parser = commands.add_parser("install", help="Preview installation; --apply writes new files only")
    install_parser.add_argument("target", type=Path)
    install_parser.add_argument("--name", required=True)
    install_parser.add_argument("--profile", choices=PROFILES, default="universal")
    install_parser.add_argument("--mode", choices=MODES, default="team")
    install_parser.add_argument("--apply", action="store_true")
    check_parser = commands.add_parser("check", help="Validate an installed protocol, not the application")
    check_parser.add_argument("target", type=Path)
    check_parser.add_argument("--strict", action="store_true", help="Also require main setup facts/commands")
    args = parser.parse_args(argv)
    try:
        if args.command == "bundle":
            count = len(manifest(root_path(BUNDLE)))
            print(f"PASS: public bundle {VERSION}, {count} files")
        elif args.command == "install":
            install(BUNDLE, args.target, args.name, args.profile, args.mode, args.apply)
        else:
            check(args.target, args.strict)
    except (ProtocolError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
