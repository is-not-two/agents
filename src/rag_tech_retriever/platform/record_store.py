"""PostgreSQL JSONB 当前记录与完整版本：原子事务、行锁、软删除、冲突保护。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from rag_tech_retriever.common.config_loader import ConfigLoader

RECORD_KINDS = {"knowledge", "plan", "agent_profile", "workflow", "workflow_run"}


def records_revision(records: list[dict]) -> str:
    """工作区版本指纹包含回收站，任意正常写操作都会改变版本。"""
    state = sorted((r["id"], r["kind"], r["version"], r["deleted"]) for r in records)
    return hashlib.sha256(json.dumps(state, separators=(",", ":")).encode()).hexdigest()


class StorageError(Exception):
    """存储不可用，不向浏览器泄漏连接细节。"""


class RecordMissing(StorageError):
    """目标不存在。"""


class VersionConflict(StorageError):
    """旧版本写入被拒绝，避免丢失其他标签页或进程的改动。"""


class RecordStore:
    """单用户工作台记录存储，table_prefix 可隔离测试与生产数据。"""

    def __init__(self, prefix: str = "workspace", config: ConfigLoader | None = None) -> None:
        """只保存配置，连接按事务创建，适合 FastAPI 多线程。"""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,42}", prefix):
            raise StorageError("非法工作台表前缀")
        self.prefix = prefix
        self.records = prefix + "_records"
        self.versions = prefix + "_versions"
        self.config = config or ConfigLoader.load_default()

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """一操作一连接，成功提交、异常回滚并释放连接。"""
        cfg = self.config
        conn = None
        try:
            conn = psycopg2.connect(
                host=cfg.env("POSTGRES_HOST", "127.0.0.1"),
                port=cfg.env("POSTGRES_PORT", "5432"),
                dbname=cfg.env("POSTGRES_DB", "rag_tech_doc"),
                user=cfg.env("POSTGRES_USER", "rag"),
                password=cfg.env("POSTGRES_PASSWORD", ""),
                connect_timeout=5,
            )
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
        except psycopg2.Error as exc:
            raise StorageError("数据库暂不可用，请检查 PostgreSQL 服务") from exc
        finally:
            if conn is not None:
                conn.close()

    def ensure_schema(self) -> None:
        """幂等创建工作台表，不触碰既有向量表和原始文档。"""
        with self.transaction() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.prefix + ":schema",))
            cur.execute(f"""CREATE TABLE IF NOT EXISTS {self.records} (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('knowledge','plan')),
                version INTEGER NOT NULL, data JSONB NOT NULL, deleted BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
            cur.execute(f"""CREATE TABLE IF NOT EXISTS {self.versions} (
                record_id TEXT NOT NULL REFERENCES {self.records}(id), version INTEGER NOT NULL,
                data JSONB NOT NULL, deleted BOOLEAN NOT NULL, action TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY(record_id,version)
            )""")
            # 事务升级旧约束；工作台记录与版本原样保留，向量表不参与。
            constraint = self.records + "_kind_check"
            cur.execute(
                "SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                "WHERE conrelid=%s::regclass AND conname=%s",
                (self.records, constraint),
            )
            row = cur.fetchone()
            if row and "workflow_run" not in row["definition"]:
                cur.execute(f"ALTER TABLE {self.records} DROP CONSTRAINT {constraint}")
            if not row or "workflow_run" not in row["definition"]:
                allowed = ",".join("'" + kind + "'" for kind in sorted(RECORD_KINDS))
                cur.execute(
                    f"ALTER TABLE {self.records} ADD CONSTRAINT {constraint} "
                    f"CHECK (kind IN ({allowed}))"
                )

    @staticmethod
    def _serialize(row: Any) -> dict:
        result = dict(row)
        for key in ("created_at", "updated_at"):
            if key in result:
                result[key] = result[key].isoformat()
        return result

    def list(
        self,
        kind: str | None = None,
        deleted: bool = False,
        limit: int | None = None,
        omit: tuple[str, ...] = (),
    ) -> list[dict]:
        """列出当前有效或回收站记录。"""
        with self.transaction() as cur:
            cur.execute(
                f"SELECT id,kind,version,data - %s::text[] AS data,deleted,created_at,updated_at "
                f"FROM {self.records} WHERE deleted=%s "
                "AND (%s IS NULL OR kind=%s) ORDER BY updated_at DESC,id LIMIT %s",
                (list(omit), deleted, kind, kind, limit),
            )
            return [self._serialize(row) for row in cur.fetchall()]

    def get(self, record_id: str, include_deleted: bool = False) -> dict:
        """读取记录，软删除默认隐藏。"""
        with self.transaction() as cur:
            cur.execute(f"SELECT * FROM {self.records} WHERE id=%s", (record_id,))
            row = cur.fetchone()
            if not row or (row["deleted"] and not include_deleted):
                raise RecordMissing("记录不存在或已移入回收站")
            return self._serialize(row)

    def _save(
        self,
        cur: Any,
        kind: str,
        data: dict,
        record_id: str,
        version: int | None,
        action: str = "save",
        deleted: bool = False,
    ) -> dict:
        cur.execute(f"SELECT * FROM {self.records} WHERE id=%s FOR UPDATE", (record_id,))
        old = cur.fetchone()
        if old:
            if version != old["version"] or kind != old["kind"]:
                raise VersionConflict("内容已更新，请刷新后再修改，避免覆盖其他版本")
            next_version = old["version"] + 1
            cur.execute(
                f"UPDATE {self.records} SET data=%s,version=%s,deleted=%s,"
                "updated_at=NOW() WHERE id=%s RETURNING *",
                (Json(data), next_version, deleted, record_id),
            )
        else:
            if version is not None:
                raise RecordMissing("记录不存在")
            next_version = 1
            cur.execute(
                f"INSERT INTO {self.records}(id,kind,version,data,deleted) "
                "VALUES(%s,%s,%s,%s,%s) RETURNING *",
                (record_id, kind, next_version, Json(data), deleted),
            )
        row = cur.fetchone()
        cur.execute(
            f"INSERT INTO {self.versions}(record_id,version,data,deleted,action) "
            "VALUES(%s,%s,%s,%s,%s)",
            (record_id, next_version, Json(data), deleted, action),
        )
        return self._serialize(row)

    def save(
        self,
        kind: str,
        data: dict,
        record_id: str | None = None,
        version: int | None = None,
    ) -> dict:
        """提交正文和历史版本；调用方先执行领域校验。"""
        if kind not in RECORD_KINDS:
            raise StorageError("不支持的记录类型")
        if record_id is not None and version is None:
            raise VersionConflict("编辑必须携带当前版本号，请刷新后重试")
        with self.transaction() as cur:
            return self._save(cur, kind, data, record_id or uuid4().hex, version)

    def save_batch(self, items: list[dict]) -> list[dict]:
        """原子保存已校验记录；按 ID 锁定，任何版本冲突回滚整批。"""
        prepared = [{**item, "id": item.get("id") or uuid4().hex} for item in items]
        if len({item["id"] for item in prepared}) != len(prepared):
            raise StorageError("批次记录 ID 重复")
        if any(item["kind"] not in RECORD_KINDS for item in prepared):
            raise StorageError("不支持的记录类型")
        with self.transaction() as cur:
            saved = {}
            for item in sorted(prepared, key=lambda item: item["id"]):
                saved[item["id"]] = self._save(
                    cur, item["kind"], item["data"], item["id"], item.get("version")
                )
            return [saved[item["id"]] for item in prepared]

    def delete(self, record_id: str, version: int) -> dict:
        """软删除仍保留完整正文、版本与恢复能力。"""
        with self.transaction() as cur:
            cur.execute(f"SELECT * FROM {self.records} WHERE id=%s FOR UPDATE", (record_id,))
            row = cur.fetchone()
            if not row:
                raise RecordMissing("记录不存在")
            return self._save(cur, row["kind"], row["data"], record_id, version, "delete", True)

    def history(self, record_id: str) -> list[dict]:
        """返回完整历史版本，包含删除和恢复操作。"""
        with self.transaction() as cur:
            cur.execute(
                f"SELECT * FROM {self.versions} WHERE record_id=%s ORDER BY version DESC",
                (record_id,),
            )
            return [self._serialize(row) for row in cur.fetchall()]

    def restore(self, record_id: str, target_version: int, current_version: int) -> dict:
        """以新版本恢复历史内容，恢复操作本身也可再次撤销。"""
        with self.transaction() as cur:
            cur.execute(f"SELECT * FROM {self.records} WHERE id=%s FOR UPDATE", (record_id,))
            row = cur.fetchone()
            if not row:
                raise RecordMissing("记录不存在")
            cur.execute(
                f"SELECT data FROM {self.versions} WHERE record_id=%s AND version=%s",
                (record_id, target_version),
            )
            target = cur.fetchone()
            if not target:
                raise RecordMissing("历史版本不存在")
            return self._save(
                cur,
                row["kind"],
                target["data"],
                record_id,
                current_version,
                f"restore:v{target_version}",
            )

    def export(self) -> dict:
        """完整可移植快照，包含历史与回收站，不导出连接密钥。"""
        with self.transaction() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute(f"SELECT * FROM {self.records} ORDER BY id")
            records = [self._serialize(row) for row in cur.fetchall()]
            cur.execute(f"SELECT * FROM {self.versions} ORDER BY record_id,version")
            versions = [self._serialize(row) for row in cur.fetchall()]
            return {"format_version": 1, "records": records, "versions": versions}

    def restore_snapshot(
        self,
        snapshot: dict,
        expected_revision: str | None = None,
        before_restore: Callable[[dict], None] | None = None,
    ) -> dict:
        """一次事务恢复整个工作台；保留当前记录的历史，不直接替换数据库文件。"""
        if snapshot.get("format_version") != 1 or not isinstance(snapshot.get("records"), list):
            raise StorageError("不支持的快照格式")
        target = {}
        for row in snapshot["records"]:
            kind = row.get("kind")
            if kind not in RECORD_KINDS or not isinstance(row.get("id"), str):
                raise StorageError("快照记录格式错误")
            if row["id"] in target:
                raise StorageError("快照存在重复 ID")
            target[row["id"]] = {
                **row,
                "deleted": bool(row.get("deleted", False)),
                "data": row["data"],
            }
        with self.transaction() as cur:
            cur.execute(f"LOCK TABLE {self.records} IN EXCLUSIVE MODE")
            cur.execute(f"SELECT * FROM {self.records} ORDER BY id")
            current = {row["id"]: row for row in cur.fetchall()}
            if (
                expected_revision is not None
                and records_revision(list(current.values())) != expected_revision
            ):
                raise VersionConflict("预览后工作区内容已改变，请重新预览，避免覆盖新修改")
            if before_restore is not None:
                cur.execute(f"SELECT * FROM {self.versions} ORDER BY record_id,version")
                protected = {
                    "format_version": 1,
                    "records": [self._serialize(row) for row in current.values()],
                    "versions": [self._serialize(row) for row in cur.fetchall()],
                }
                before_restore(protected)
            count = 0
            for record_id in sorted(current.keys() | target.keys()):
                old = current.get(record_id)
                desired = target.get(record_id)
                if desired is None:
                    if old["deleted"]:
                        continue
                    self._save(
                        cur,
                        old["kind"],
                        old["data"],
                        record_id,
                        old["version"],
                        "snapshot:remove",
                        True,
                    )
                else:
                    if (
                        old
                        and old["kind"] == desired["kind"]
                        and old["data"] == desired["data"]
                        and old["deleted"] == desired["deleted"]
                    ):
                        continue
                    self._save(
                        cur,
                        desired["kind"],
                        desired["data"],
                        record_id,
                        old["version"] if old else None,
                        "snapshot:restore",
                        bool(desired.get("deleted", False)),
                    )
                count += 1
            return {"restored_records": count}
