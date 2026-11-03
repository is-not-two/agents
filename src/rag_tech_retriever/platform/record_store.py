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
from rag_tech_retriever.common.schema_policy import configured_schema_mode, schema_timeouts
from rag_tech_retriever.platform.field_crypto import CryptoError, FieldCipher
from rag_tech_retriever.platform.workspace_schema import (
    SchemaValidationError,
    managed_kind_check,
    verify_workspace_schema,
)

RECORD_KINDS = {
    "knowledge",
    # 网页收藏：独立分类与可点击外链（2026-11-03 起）。
    "bookmark",
    "plan",
    "agent_profile",
    "workflow",
    "workflow_run",
    # 谨记名单：个人错题/教训，按类型分类（2026-10-24 起）。
    "lesson",
    "job_lead", "application", "interview_report", "resume_version", "company_capability",
    "learning_card", "learning_review", "notification_outbox", "agent_memory", "agent_session",
    # 私密管理：愿望清单与日记。加密在应用层完成，这里只存密文，
    # 因此不与普通内容混用同一字段语义。
    "wish",
    "diary",
}
# 外发意图不能进入公共恢复，否则恢复旧备份可能重发消息。
WORKSPACE_KINDS = RECORD_KINDS - {"wish", "diary", "notification_outbox", "agent_memory", "agent_session"}


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
        try:
            self.cipher = FieldCipher.from_config(self.config, RECORD_KINDS)
        except CryptoError as exc:
            raise StorageError(str(exc)) from exc

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

    def ping(self, timeout_seconds: int = 3) -> None:
        """Probe PostgreSQL with bounded connection/statement timeouts and no writes."""
        if (not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool)
                or not 2 <= timeout_seconds <= 10):
            raise ValueError("探针超时必须在 2–10 秒之间")
        cfg = self.config
        conn = None
        try:
            conn = psycopg2.connect(
                host=cfg.env("POSTGRES_HOST", "127.0.0.1"),
                port=cfg.env("POSTGRES_PORT", "5432"),
                dbname=cfg.env("POSTGRES_DB", "rag_tech_doc"),
                user=cfg.env("POSTGRES_USER", "rag"),
                password=cfg.env("POSTGRES_PASSWORD", ""),
                connect_timeout=timeout_seconds,
                options=f"-c statement_timeout={timeout_seconds * 1000}",
            )
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except psycopg2.Error as exc:
            raise StorageError("数据库就绪检查失败") from exc
        finally:
            if conn is not None:
                conn.close()

    def ensure_schema(self) -> None:
        """Local auto-init remains compatible; production/direct scripts only verify."""
        profile, mode = configured_schema_mode(self.config)
        if mode == "verify":
            self.verify_schema(require_runtime_role=profile == "production")
            return
        self._apply_schema()

    def verify_schema(self, *, require_runtime_role: bool = False) -> dict:
        """Check schema/permissions without DDL, row writes or migration fallback."""
        timeouts = schema_timeouts(self.config)
        try:
            with self.transaction() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(f"SET LOCAL statement_timeout = {timeouts['schema_verify_timeout_ms']}")
                return verify_workspace_schema(cur, self.records, self.versions, RECORD_KINDS,
                                               require_runtime_role=require_runtime_role)
        except SchemaValidationError as exc:
            raise StorageError(str(exc)) from None

    def migrate_schema(self, confirmation: str) -> dict:
        """Explicit operator path; no deletion or automatic data/schema repair."""
        if confirmation != "仅创建或升级工作台结构，不删除记录":
            raise StorageError("结构迁移需要完整确认文字")
        self._apply_schema()
        return {"migrated": True, "tables": [self.records, self.versions], "records_deleted": 0}

    def _apply_schema(self) -> None:
        """One administrator/local transaction, checked before commit; never called in verify mode."""
        try:
            self._apply_schema_transaction()
        except SchemaValidationError as exc:
            raise StorageError(str(exc)) from None

    def _apply_schema_transaction(self) -> None:
        timeouts = schema_timeouts(self.config)
        with self.transaction() as cur:
            cur.execute(f"SET LOCAL lock_timeout = {timeouts['schema_lock_timeout_ms']}")
            cur.execute(f"SET LOCAL statement_timeout = {timeouts['schema_migration_timeout_ms']}")
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.prefix + ":schema",))
            cur.execute("SELECT to_regclass(%s) AS records,to_regclass(%s) AS versions", (self.records, self.versions))
            existing = cur.fetchone()
            if existing["records"] and not existing["versions"]:
                cur.execute(f"SELECT 1 FROM {self.records} LIMIT 1")
                if cur.fetchone():
                    raise SchemaValidationError("非空记录表缺少历史表，不能用空历史掩盖丢失；请管理员核对备份")
            if existing["versions"] and not existing["records"]:
                raise SchemaValidationError("历史表缺少所属记录表，请管理员核对备份")
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
            constraint = self.records.lower() + "_kind_check"
            verify_workspace_schema(cur, self.records, self.versions, RECORD_KINDS, verify_kind=False)
            cur.execute(
                "SELECT pg_get_expr(conbin,conrelid) AS expression,convalidated FROM pg_constraint "
                "WHERE conrelid=%s::regclass AND conname=%s",
                (self.records, constraint),
            )
            row = cur.fetchone()
            # 约束需要覆盖当前全部 kind；任一缺失即重建
            complete = bool(row and row["convalidated"] and managed_kind_check(row["expression"], RECORD_KINDS))
            if row and not complete:
                cur.execute(f"ALTER TABLE {self.records} DROP CONSTRAINT {constraint}")
            if not complete:
                allowed = ",".join("'" + kind + "'" for kind in sorted(RECORD_KINDS))
                cur.execute(
                    f"ALTER TABLE {self.records} ADD CONSTRAINT {constraint} "
                    f"CHECK (kind IN ({allowed}))"
                )
            verify_workspace_schema(cur, self.records, self.versions, RECORD_KINDS)

    def _open(self, kind: object, data: object) -> dict:
        """读取时解密配置字段；旧明文记录与未配置类型原样返回。"""
        if not self.cipher or not isinstance(kind, str) or not isinstance(data, dict):
            return data
        try:
            return self.cipher.open(kind, data)
        except CryptoError as exc:
            raise StorageError(str(exc)) from exc

    def _serialize(self, row: Any) -> dict:
        result = dict(row)
        if isinstance(result.get("data"), dict):
            result["data"] = self._open(result.get("kind"), result["data"])
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
        data_kinds: tuple[str, ...] = (),
    ) -> list[dict]:
        """列出当前有效或回收站记录。"""
        with self.transaction() as cur:
            cur.execute(
                f"SELECT id,kind,version,data - %s::text[] AS data,deleted,created_at,updated_at "
                f"FROM {self.records} WHERE deleted=%s "
                "AND (%s IS NULL OR kind=%s) "
                "AND (%s::text[]='{}'::text[] OR data->>'kind'=ANY(%s::text[])) "
                "ORDER BY updated_at DESC,id LIMIT %s",
                (list(omit), deleted, kind, kind, list(data_kinds), list(data_kinds), limit),
            )
            return [self._serialize(row) for row in cur.fetchall()]

    def count(self, kind: str, deleted: bool = False) -> int:
        """只做计数，不读取 JSONB 正文；用于状态卡和统计接口。"""
        if kind not in RECORD_KINDS:
            raise StorageError("不支持的记录类型")
        with self.transaction() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS total FROM {self.records} WHERE deleted=%s AND kind=%s",
                (deleted, kind),
            )
            return int(cur.fetchone()["total"])

    def kind_counts(self, kinds: set[str] | None = None) -> dict[str, dict[str, int]]:
        """一次分组查询返回各类型有效/回收站数量，避免逐类型全表读取。"""
        selected = sorted(kinds or WORKSPACE_KINDS)
        if not selected or any(kind not in RECORD_KINDS for kind in selected):
            raise StorageError("统计类型不合法")
        with self.transaction() as cur:
            cur.execute(
                f"SELECT kind,deleted,COUNT(*) AS total FROM {self.records} "
                "WHERE kind=ANY(%s::text[]) GROUP BY kind,deleted",
                (selected,),
            )
            rows = cur.fetchall()
        result = {kind: {"active": 0, "trash": 0} for kind in selected}
        for row in rows:
            bucket = "trash" if row["deleted"] else "active"
            result[row["kind"]][bucket] = int(row["total"])
        return result

    def plan_stats(self) -> dict[str, int]:
        """聚合规划节点总数与完成数，避免状态接口把整份规划读进内存。

        口径与 ``domains.life_planning`` 的内存统计一致：只计有效记录，
        ``data.acts[].nodes[]`` 展开后按布尔 ``done`` 计数；缺失字段视为未完成。
        """
        with self.transaction() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS node_count,"
                f" COALESCE(SUM(CASE WHEN COALESCE((node->>'done')::boolean,false)"
                f" THEN 1 ELSE 0 END),0) AS done_count"
                f" FROM {self.records} AS r"
                " CROSS JOIN LATERAL jsonb_array_elements("
                "COALESCE(r.data->'acts','[]'::jsonb)) AS act"
                " CROSS JOIN LATERAL jsonb_array_elements("
                "COALESCE(act->'nodes','[]'::jsonb)) AS node"
                " WHERE r.kind='plan' AND NOT r.deleted"
            )
            row = cur.fetchone()
        return {"node_count": int(row["node_count"]), "done_count": int(row["done_count"])}

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
        stored = self.cipher.seal(kind, data) if self.cipher else data
        if old:
            if version != old["version"] or kind != old["kind"]:
                raise VersionConflict("内容已更新，请刷新后再修改，避免覆盖其他版本")
            next_version = old["version"] + 1
            cur.execute(
                f"UPDATE {self.records} SET data=%s,version=%s,deleted=%s,"
                "updated_at=NOW() WHERE id=%s RETURNING *",
                (Json(stored), next_version, deleted, record_id),
            )
        else:
            if version is not None:
                raise RecordMissing("记录不存在")
            next_version = 1
            cur.execute(
                f"INSERT INTO {self.records}(id,kind,version,data,deleted) "
                "VALUES(%s,%s,%s,%s,%s) RETURNING *",
                (record_id, kind, next_version, Json(stored), deleted),
            )
        row = cur.fetchone()
        cur.execute(
            f"INSERT INTO {self.versions}(record_id,version,data,deleted,action) "
            "VALUES(%s,%s,%s,%s,%s)",
            (record_id, next_version, Json(stored), deleted, action),
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
                f"SELECT v.*,r.kind FROM {self.versions} v JOIN {self.records} r ON r.id=v.record_id "
                "WHERE v.record_id=%s ORDER BY v.version DESC",
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
                self._open(row["kind"], target["data"]),
                record_id,
                current_version,
                f"restore:v{target_version}",
            )

    def export(self) -> dict:
        """公共工作区快照包含历史与回收站；私密内容及连接密钥独立备份。"""
        with self.transaction() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute(
                f"SELECT * FROM {self.records} WHERE kind=ANY(%s) ORDER BY id",
                (sorted(WORKSPACE_KINDS),),
            )
            records = [self._serialize(row) for row in cur.fetchall()]
            cur.execute(
                f"SELECT v.*,r.kind FROM {self.versions} v JOIN {self.records} r ON r.id=v.record_id "
                "WHERE r.kind=ANY(%s) ORDER BY v.record_id,v.version",
                (sorted(WORKSPACE_KINDS),),
            )
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
            if kind not in WORKSPACE_KINDS or not isinstance(row.get("id"), str):
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
            all_current = {row["id"]: row for row in cur.fetchall()}
            private_ids = {key for key, row in all_current.items() if row["kind"] not in WORKSPACE_KINDS}
            if private_ids & target.keys():
                raise VersionConflict("备份记录 ID 与私密条目冲突，无法恢复")
            current = {key: row for key, row in all_current.items() if key not in private_ids}
            if (
                expected_revision is not None
                and records_revision(list(current.values())) != expected_revision
            ):
                raise VersionConflict("预览后工作区内容已改变，请重新预览，避免覆盖新修改")
            if before_restore is not None:
                cur.execute(
                    f"SELECT v.*,r.kind FROM {self.versions} v JOIN {self.records} r ON r.id=v.record_id "
                    "WHERE r.kind=ANY(%s) ORDER BY v.record_id,v.version",
                    (sorted(WORKSPACE_KINDS),),
                )
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
                        self._open(old["kind"], old["data"]),
                        record_id,
                        old["version"],
                        "snapshot:remove",
                        True,
                    )
                else:
                    if (
                        old
                        and old["kind"] == desired["kind"]
                        and self._open(old["kind"], old["data"]) == desired["data"]
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
