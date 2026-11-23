"""Deterministic, allowlisted source manifests; never collect private workspace data."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT_FILES = {"pyproject.toml", "requirements.txt", "README.md", "Dockerfile",
              "docker-compose.yml", ".env.example", ".gitignore",
              "data/processed/agent_golden_set.json", "data/processed/collaboration_tasks.json"}
ROOT_DIRS = {"src", "config", "scripts", "tests", ".github", "docs"}
VUE_FILES = {"shilie/" + name for name in (
    "index.html", "package.json", "package-lock.json", "tsconfig.json", "vite.config.ts", "README.md",
)}
VUE_DIRS = {"shilie/src", "shilie/public", "shilie/scripts"}
VUE_SUFFIXES = {".ts", ".vue", ".mjs", ".js", ".css", ".json", ".webp", ".svg", ".woff2"}
STATIC_PREFIX = "src/rag_tech_retriever/api/static/"
VUE_PREFIX = STATIC_PREFIX + "vue/"
VUE_ASSET = re.compile(r"(?:index\.html|assets/[A-Za-z0-9_.-]+\.(?:js|css|webp|svg|woff2)|wallpaper/[A-Za-z0-9_.-]+\.webp)\Z")


def vue_manifest(directory: Path) -> dict[str, str]:
    """Fingerprint a candidate's exact runtime bytes, not dependencies or local files."""
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("缺少已验收的 Vue 构建目录")
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Vue 构建目录不允许符号链接")
        if path.is_dir():
            continue
        relative = path.relative_to(directory).as_posix()
        if not path.is_file() or not VUE_ASSET.fullmatch(relative):
            raise ValueError("Vue 构建目录含无效资源")
        result[VUE_PREFIX + relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if VUE_PREFIX + "index.html" not in result or not any(name.endswith(".js") for name in result):
        raise ValueError("Vue 构建目录缺少首页或脚本")
    return result


def source_manifest(root: Path) -> dict[str, str]:
    """Hash source-only regular files; reject symlinks instead of following them."""
    result = {}
    for top in sorted(ROOT_FILES | ROOT_DIRS | VUE_FILES | VUE_DIRS):
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
            if top in VUE_DIRS and (path.suffix not in VUE_SUFFIXES
                                    or any(part.startswith(".") for part in path.relative_to(start).parts)):
                continue
            if path.name == ".env" or path.suffix in {".pyc", ".png", ".dump"}:
                continue
            name = path.relative_to(root).as_posix()
            if name.startswith(VUE_PREFIX):
                continue
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result
