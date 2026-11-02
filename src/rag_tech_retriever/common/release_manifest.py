"""Deterministic, allowlisted source manifests; never collect private workspace data."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT_FILES = {"pyproject.toml", "requirements.txt", "README.md", "Dockerfile",
              "docker-compose.yml", ".env.example", ".gitignore",
              "data/processed/agent_golden_set.json", "data/processed/collaboration_tasks.json"}
ROOT_DIRS = {"src", "config", "scripts", "tests", ".github", "docs"}


def source_manifest(root: Path) -> dict[str, str]:
    """Hash source-only regular files; reject symlinks instead of following them."""
    result = {}
    for top in sorted(ROOT_FILES | ROOT_DIRS):
        start = root / top
        if not start.resolve().is_relative_to(root.resolve()):
            raise ValueError("发布源不能越出工作区")
        for parent in start.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError("发布源的父目录不允许符号链接")
        if start.is_symlink():
            raise ValueError("发布源不允许符号链接")
        if not start.exists():
            continue
        targets = sorted(start.rglob("*")) if start.is_dir() else [start]
        for path in targets:
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("发布源不能越出工作区")
            if path.is_symlink():
                raise ValueError("发布源不允许符号链接")
            if not path.is_file() or "__pycache__" in path.parts or "_archived" in path.parts:
                continue
            if path.name == ".env" or path.suffix in {".pyc", ".png", ".dump"}:
                continue
            name = path.relative_to(root).as_posix()
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result
