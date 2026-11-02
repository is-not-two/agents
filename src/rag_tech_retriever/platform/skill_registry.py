"""Bounded SKILL.md import and discovery; never execute bundled code."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
from pathlib import Path

import yaml

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.record_store import RecordMissing, StorageError, VersionConflict

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def valid_name(name: str) -> bool:
    """Portable skill/server identifiers, not arbitrary file paths."""
    return isinstance(name, str) and len(name) <= 64 and bool(NAME.fullmatch(name))


class SkillRegistry:
    """Skills are server-side assets; import only Markdown, not archives or commands."""

    def __init__(self, directory: Path, maximum: int = 65536) -> None:
        self.directory = directory.resolve()
        self.maximum = maximum
        self._mutex = threading.RLock()

    def _path(self, name: str) -> Path:
        if not valid_name(name):
            raise DomainError("技能名称只允许小写字母、数字和单个连字符，最多64字符")
        path = self.directory / name / "SKILL.md"
        if not path.resolve().is_relative_to(self.directory) or path.parent.is_symlink() or path.is_symlink():
            raise DomainError("技能路径不在允许目录内")
        return path

    def _parse(self, name: str, raw: bytes) -> dict:
        if len(raw) > self.maximum:
            raise DomainError("技能文件超过大小限制")
        try:
            content = raw.decode("utf-8")
            lines = content.splitlines()
            if not lines or lines[0] != "---":
                raise ValueError
            end = lines.index("---", 1)
            meta = yaml.safe_load("\n".join(lines[1:end]))
            body = "\n".join(lines[end + 1:]).strip()
            if not isinstance(meta, dict) or meta.get("name") != name:
                raise ValueError
            description = meta.get("description")
            if not isinstance(description, str) or not 0 < len(description.strip()) <= 2000 or not body:
                raise ValueError
        except (UnicodeError, ValueError, yaml.YAMLError) as exc:
            raise DomainError("SKILL.md需要匹配的name、description及非空正文") from exc
        return {"name": name, "description": description.strip(), "instructions": body,
                "revision": hashlib.sha256(raw).hexdigest(), "content": content}

    def get(self, name: str) -> dict:
        """Read a skill with byte limit and stable content hash."""
        path = self._path(name)
        try:
            with path.open("rb") as stream:
                return self._parse(name, stream.read(self.maximum + 1))
        except FileNotFoundError as exc:
            raise RecordMissing("技能不存在") from exc
        except OSError as exc:
            raise StorageError("无法读取技能文件") from exc

    def list(self) -> list[dict]:
        """Small catalog only; malformed externally-installed files fail explicitly."""
        if not self.directory.exists():
            return []
        result = []
        for path in sorted(self.directory.iterdir()):
            if path.is_dir() and (path / "SKILL.md").exists():
                skill = self.get(path.name)
                result.append({key: skill[key] for key in ("name", "description", "revision")})
            if len(result) > 200:
                raise DomainError("技能数量超过200，请清理或分开配置")
        return result

    def save(self, name: str, content: str, revision: str | None) -> dict:
        """CAS update under a cross-process file lock; no arbitrary auxiliary files."""
        path = self._path(name)
        raw = content.encode("utf-8")
        skill = self._parse(name, raw)
        temporary = None
        with self._mutex:
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / ".registry.lock").open("a+b") as lock:
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    current = self.get(name)["revision"] if path.exists() else None
                    if current != revision:
                        raise VersionConflict("技能已存在或已更新，请重新读取revision后保存")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    fd, temporary = tempfile.mkstemp(prefix=".skill-", dir=path.parent)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, path)
                finally:
                    if temporary:
                        Path(temporary).unlink(missing_ok=True)
                    lock.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock, fcntl.LOCK_UN)
        return skill
