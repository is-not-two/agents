"""阶段日志、受限源码快照、SHA-256 冲突检测和默认只读的回滚预检。"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

SOURCE_DIRS = ("src", "scripts", "config", "tests", "output/v1", "output/v1.5")
SOURCE_SUFFIXES = {
    ".py",
    ".yaml",
    ".md",
    ".json",
    ".html",
    ".css",
    ".js",
    ".ps1",
    ".svg",
    ".webp",
    ".png",
}
ROOT_FILES = (
    "AGENTS.md",
    "DESIGN.md",
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "docker-compose.yml",
    "Dockerfile",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "start-web.ps1",
    "stop-web.ps1",
    "output/metrics_ledger.jsonl",
    "output/metrics_summary.md",
)


def timestamp() -> str:
    """以用户时区 UTC+8 记录时间。"""
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def write_json(path: Path, value: Any) -> None:
    """临时文件 + 原子替换，不留下部分 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest(path: Path) -> str | None:
    """返回现存文件摘要，不存在返回 None。"""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class JournalError(Exception):
    """阶段不存在、快照损坏或存在未被覆盖授权的后续改动。"""


class StageJournal:
    """项目大阶段的完成项/问题/验证记录及实现前快照。"""

    def __init__(self, root: Path, directory: Path) -> None:
        """显式指定项目与快照根路径，测试可注入临时目录。"""
        self.root = root.resolve()
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _folder(self, stage_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", stage_id):
            raise JournalError("非法阶段 ID")
        return self.directory / stage_id

    def _path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        allowed = relative in ROOT_FILES or any(
            relative.startswith(folder + "/") for folder in SOURCE_DIRS
        )
        if not allowed or not path.is_relative_to(self.root) or path == self.root:
            raise JournalError(f"快照包含越界路径：{relative}")
        if path.name == ".env" or "__pycache__" in path.parts:
            raise JournalError("不能回滚密钥或缓存")
        return path

    def source_files(self) -> dict[str, str]:
        """只扫描明确列出的源码目录，忽略依赖和用户数据。"""
        paths: set[Path] = set()
        for folder in SOURCE_DIRS:
            if (self.root / folder).is_dir():
                paths.update(
                    p
                    for p in (self.root / folder).rglob("*")
                    if p.is_file() and p.suffix in SOURCE_SUFFIXES and "__pycache__" not in p.parts
                )
        paths.update(self.root / name for name in ROOT_FILES if (self.root / name).is_file())
        return {p.relative_to(self.root).as_posix(): str(digest(p)) for p in sorted(paths)}

    def start(self, title: str, objective: str, snapshot: dict | None = None) -> dict:
        """先保存源码和可选数据快照，再产生可见阶段记录。"""
        if not title.strip():
            raise JournalError("阶段名称不能为空")
        stage_id = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S-")
        stage_id += uuid4().hex[:8]
        folder = self._folder(stage_id)
        self.write_recovery_capsule(stage_id)
        before = self.source_files()
        for name in before:
            target = folder / "before" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self._path(name), target)
        if snapshot is not None:
            write_json(folder / "data_snapshot.json", snapshot)
        record = {
            "id": stage_id,
            "title": title.strip(),
            "objective": objective.strip(),
            "status": "running",
            "created_at": timestamp(),
            "completed_at": None,
            "completed": [],
            "issues": [],
            "verification": [],
            "before": before,
            "after": {},
            "changes": [],
            "data_snapshot_available": snapshot is not None,
        }
        write_json(folder / "record.json", record)
        return record

    def write_recovery_capsule(self, stage_id: str) -> Path:
        """保存仅依赖标准库的恢复工具，源码回滚删除包后仍能恢复保护快照。"""
        folder = self._folder(stage_id)
        folder.mkdir(parents=True, exist_ok=True)
        marker = "\n# Recovery " + "entrypoint\n"
        source = Path(__file__).read_text(encoding="utf-8").split(marker, 1)[0]
        entrypoint = f"""{marker}
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="独立源码恢复；默认预检，--apply 才应用")
    parser.add_argument("--id", default={stage_id!r})
    parser.add_argument("--root", type=Path, default=Path({str(self.root)!r}))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    journal = StageJournal(args.root, Path(__file__).resolve().parent.parent)
    print(json.dumps(journal.rollback(args.id, args.apply), ensure_ascii=False, indent=2))
"""
        target = folder / "recover_source.py"
        target.write_text(source + entrypoint, encoding="utf-8")
        return target

    def get(self, stage_id: str) -> dict:
        """读取一个阶段，不存在时给出可识别错误。"""
        path = self._folder(stage_id) / "record.json"
        if not path.is_file():
            raise JournalError("阶段记录不存在")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        """按时间倒序列出阶段，摘要包含真实文件改动及回滚预检命令。"""
        records = [self.get(p.parent.name) for p in self.directory.glob("*/record.json")]
        return sorted(records, key=lambda row: row["created_at"], reverse=True)

    def finish(
        self,
        stage_id: str,
        completed: list[str],
        issues: list[str],
        verification: list[str],
        status: str = "passed",
    ) -> dict:
        """记录完成证据与前后文件摘要，不将未验证阶段自动标为通过。"""
        if status not in {"passed", "attention"}:
            raise JournalError("阶段结果必须是 passed 或 attention")
        record = self.get(stage_id)
        if record["status"] != "running":
            raise JournalError("已结束阶段不可重写，请新建后续阶段")
        after = self.source_files()
        before = record["before"]
        changes = [
            {
                "path": name,
                "kind": "added"
                if name not in before
                else "deleted"
                if name not in after
                else "modified",
                "before_sha256": before.get(name),
                "after_sha256": after.get(name),
            }
            for name in sorted(before.keys() | after.keys())
            if before.get(name) != after.get(name)
        ]
        patches = []
        for change in changes:
            name = change["path"]
            if Path(name).suffix in {".webp", ".png"}:
                patches.append(f"Binary asset changed: {name}\n")
                continue
            backup = self._folder(stage_id) / "before" / name
            target = self._path(name)
            old = (
                backup.read_text(encoding="utf-8", errors="replace").splitlines(True)
                if backup.is_file()
                else []
            )
            new = (
                target.read_text(encoding="utf-8", errors="replace").splitlines(True)
                if target.is_file()
                else []
            )
            patches.extend(
                difflib.unified_diff(old, new, fromfile="before/" + name, tofile="after/" + name)
            )
        (self._folder(stage_id) / "changes.patch").write_text("".join(patches), encoding="utf-8")
        record.update(
            status=status,
            completed=completed,
            issues=issues,
            verification=verification,
            after=after,
            changes=changes,
            completed_at=timestamp(),
        )
        write_json(self._folder(stage_id) / "record.json", record)
        return record

    def rollback(self, stage_id: str, apply: bool = False) -> dict:
        """默认预检；仅当当前内容等于本阶段完成状态、备份完整时允许应用。"""
        record = self.get(stage_id)
        if record["status"] not in {"passed", "attention"}:
            raise JournalError("只能回滚已结束的阶段")
        conflicts = []
        for change in record["changes"]:
            name = change["path"]
            target = self._path(name)
            if digest(target) != change["after_sha256"]:
                conflicts.append(name + "：存在后续改动")
            if change["before_sha256"] is not None:
                backup = self._folder(stage_id) / "before" / name
                if digest(backup) != change["before_sha256"]:
                    conflicts.append(name + "：实现前备份损坏")
        plan = {
            "stage_id": stage_id,
            "apply": apply,
            "changes": record["changes"],
            "conflicts": conflicts,
            "can_apply": not conflicts,
        }
        if not apply:
            return plan
        if conflicts:
            raise JournalError("回滚拒绝：" + "；".join(conflicts))
        rescue = self.start("回滚前保护快照 · " + record["title"], "保留回滚前当前源码")
        for change in record["changes"]:
            target = self._path(change["path"])
            if change["before_sha256"] is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".restore.tmp")
                shutil.copy2(self._folder(stage_id) / "before" / change["path"], temporary)
                temporary.replace(target)
        record["status"] = "rolled_back"
        record["rollback_at"] = timestamp()
        record["rescue_stage_id"] = rescue["id"]
        write_json(self._folder(stage_id) / "record.json", record)
        self.finish(rescue["id"], ["执行源码回滚并保留回滚前副本"], [], ["SHA-256 预检通过"])
        plan["rescue_stage_id"] = rescue["id"]
        return plan

    def data_snapshot(self, stage_id: str) -> dict:
        """返回阶段开始时的数据快照，调用方以新版本事务恢复。"""
        record = self.get(stage_id)
        if not record.get("data_snapshot_available"):
            raise JournalError("此阶段没有数据快照")
        return json.loads(
            (self._folder(stage_id) / "data_snapshot.json").read_text(encoding="utf-8")
        )

# Recovery entrypoint

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="独立源码恢复；默认预检，--apply 才应用")
    parser.add_argument("--id", default='20261015-094813-f0529244')
    parser.add_argument("--root", type=Path, default=Path('E:\\project\\agents\\rag-tech-doc-retriever\\output\\web\\qa-runtime-data'))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    journal = StageJournal(args.root, Path(__file__).resolve().parent.parent)
    print(json.dumps(journal.rollback(args.id, args.apply), ensure_ascii=False, indent=2))
