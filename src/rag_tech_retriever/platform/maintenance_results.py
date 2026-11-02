"""Check scheduled executor contracts against actual source-file changes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SOURCE_DIRS = ("src", "scripts", "tests", "config")
ROOT_FILES = ("README.md", "DESIGN.md", "AGENTS.md", "pyproject.toml", "requirements.txt",
              "start-web.ps1", "stop-web.ps1", "Dockerfile", "docker-compose.yml",
              ".gitignore", ".dockerignore", ".env.example")
SUFFIXES = {".py", ".json", ".yaml", ".yml", ".js", ".css", ".html", ".svg", ".ps1",
            ".md", ".png", ".webp"}
FIELDS = {"status", "summary", "changes", "verification", "rollback_ids", "reasons"}
STATUSES = {"completed_changes", "checked_no_changes", "blocked", "failed"}


def source_snapshot(root: Path) -> dict[str, str]:
    """Hash source/config/test files, excluding secrets, data, logs and symlink escapes."""
    root = root.resolve()
    paths = [root / name for name in ROOT_FILES]
    for folder in SOURCE_DIRS:
        paths.extend((root / folder).rglob("*"))
    result = {}
    for path in paths:
        if (path.suffix not in SUFFIXES and path.name not in ROOT_FILES) or not path.is_file():
            continue
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or not path.resolve().is_relative_to(root):
            continue
        with path.open("rb") as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(65_536), b""):
                digest.update(block)
        result[relative.as_posix()] = digest.hexdigest()
    return result


def classify_result(
    result_file: Path, exit_code: int, before: dict[str, str], after: dict[str, str],
) -> dict:
    """Process success alone is never task success; verification remains executor-reported."""
    changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    details = {"exit_code": exit_code, "observed_changes": changed, "contract_version": 1,
               "verification_source": "executor_reported"}
    if exit_code != 0:
        return {**details, "status": "failed_execution"}
    try:
        with result_file.open("rb") as stream:
            raw = stream.read(65_537)
        if len(raw) > 65_536:
            raise ValueError("oversize_result")
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != FIELDS:
            raise ValueError("invalid_fields")
        if value["status"] not in STATUSES or not isinstance(value["summary"], str):
            raise ValueError("invalid_status")
        for field in ("changes", "verification", "rollback_ids", "reasons"):
            if not isinstance(value[field], list) or any(
                not isinstance(item, str) or not item.strip() for item in value[field]
            ):
                raise ValueError("invalid_list")
        if len(set(value["changes"])) != len(value["changes"]) or set(value["changes"]) != set(changed):
            raise ValueError("change_manifest_mismatch")
        if value["status"] == "completed_changes" and (
            not changed or not value["verification"] or not value["rollback_ids"]
        ):
            raise ValueError("unverified_completion")
        if value["status"] == "checked_no_changes" and (changed or not value["verification"]):
            raise ValueError("unverified_check")
        return {**details, **value}
    except (OSError, ValueError, TypeError, UnicodeError):
        return {**details, "status": "failed_contract", "reason": "missing_or_inconsistent_result"}
