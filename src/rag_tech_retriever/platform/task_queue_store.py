"""任务队列的 PostgreSQL 读写：入队、领取、回写、检查点与死信。

复用 RecordStore 的连接池与事务边界（store.transaction()），不另开连接管理。
表名沿用工作台前缀（workspace_task_jobs），与记录表同 schema。

并发要点：领取任务用 `FOR UPDATE SKIP LOCKED`，多个 worker 同时跑也不会
拿到同一条任务；租约过期的 running 任务会被重新领取，因此 worker 崩溃
不会让任务永远卡在「执行中」。
"""

from __future__ import annotations

from psycopg2.extras import Json

from rag_tech_retriever.domains.task_queue import (
    CANCELLED,
    DEAD,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    failure_outcome,
    next_run_at,
    utcnow,
)
from rag_tech_retriever.platform.record_store import RecordStore

# 领取顺序：优先级高的先跑，同优先级按计划时间先后。
CLAIM_ORDER = "ORDER BY priority DESC, next_run_at ASC"

DDL_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS {table} (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        priority INTEGER NOT NULL DEFAULT 50,
        payload JSONB NOT NULL,
        result JSONB,
        checkpoint JSONB,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        lease_until TIMESTAMPTZ,
        next_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_error TEXT,
        idempotency_key TEXT,
        worker_id TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS {table}_ready_idx ON {table} (status, next_run_at)",
    """CREATE UNIQUE INDEX IF NOT EXISTS {table}_idempotency_idx
        ON {table} (idempotency_key) WHERE idempotency_key IS NOT NULL""",
)


def claim_sql(table: str) -> str:
    """领取语句：跳过已被别的 worker 锁定的行，并顺带回收过期租约。"""
    return f"""UPDATE {table} SET status = '{RUNNING}', attempts = attempts + 1,
        lease_until = NOW() + (%(lease_seconds) || ' seconds')::interval,
        worker_id = %(worker_id)s, updated_at = NOW()
        WHERE id = (
            SELECT id FROM {table}
            WHERE (status = '{QUEUED}' AND next_run_at <= NOW())
               OR (status = '{RUNNING}' AND lease_until IS NOT NULL AND lease_until <= NOW())
            {CLAIM_ORDER}
            FOR UPDATE SKIP LOCKED LIMIT 1
        )
        RETURNING *"""


class TaskQueueStore:
    """队列数据访问；DDL 只在管理员或本地路径执行。"""

    def __init__(self, store: RecordStore) -> None:
        self.store = store
        self.table = store.prefix + "_task_jobs"

    # ---------- 结构 ----------

    def ensure_table(self) -> list[str]:
        """建表与索引；生产运行账号无 CREATE 权限，这里只给迁移脚本与本地用。"""
        applied = []
        with self.store.transaction() as cur:
            for statement in DDL_STATEMENTS:
                cur.execute(statement.format(table=self.table))
                applied.append(statement.split("\n")[0][:60])
        return applied

    def table_exists(self) -> bool:
        """只读探测：队列表是否已就绪。"""
        with self.store.transaction() as cur:
            cur.execute("SELECT to_regclass(%s) AS table", (self.table,))
            return cur.fetchone()["table"] is not None

    # ---------- 写入 ----------

    def enqueue(self, job_id: str, kind: str, payload: dict, *, max_attempts: int = 3,
                priority: int = 50, idempotency_key: str | None = None) -> dict:
        """入队；带幂等键时重复提交返回既有任务，不会产生第二条。"""
        with self.store.transaction() as cur:
            cur.execute(
                f"""INSERT INTO {self.table}
                    (id, kind, status, priority, payload, attempts, max_attempts,
                     next_run_at, idempotency_key)
                    VALUES (%(id)s, %(kind)s, '{QUEUED}', %(priority)s, %(payload)s, 0,
                            %(max_attempts)s, NOW(), %(idempotency_key)s)
                    ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                    DO NOTHING RETURNING *""",
                {"id": job_id, "kind": kind, "priority": priority, "payload": Json(payload),
                 "max_attempts": max_attempts, "idempotency_key": idempotency_key},
            )
            row = cur.fetchone()
            if row is not None:
                return dict(row)
            cur.execute(f"SELECT * FROM {self.table} WHERE idempotency_key = %s",
                        (idempotency_key,))
            existing = cur.fetchone()
            if existing is None:
                raise RuntimeError("任务入队失败：幂等冲突但找不到既有任务")
            return dict(existing)

    def claim(self, worker_id: str, lease_seconds: int = 900) -> dict | None:
        """领取一条就绪任务；没有可领的返回 None。"""
        with self.store.transaction() as cur:
            cur.execute(claim_sql(self.table),
                        {"worker_id": worker_id, "lease_seconds": lease_seconds})
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def complete(self, job_id: str, result: dict) -> None:
        """任务成功：写结果、清租约。"""
        with self.store.transaction() as cur:
            cur.execute(
                f"""UPDATE {self.table} SET status = '{SUCCEEDED}', result = %(result)s,
                    lease_until = NULL, last_error = NULL, updated_at = NOW()
                    WHERE id = %(id)s""",
                {"id": job_id, "result": Json(result)},
            )

    def mark_cancelled(self, job_id: str, result: dict) -> None:
        """任务被中途取消：落 cancelled 状态。

        不能复用 complete()——那会把状态写成 succeeded，
        用户明明取消了，列表里却显示「已完成」。
        """
        with self.store.transaction() as cur:
            cur.execute(
                f"""UPDATE {self.table} SET status = '{CANCELLED}', result = %(result)s,
                    lease_until = NULL, updated_at = NOW() WHERE id = %(id)s""",
                {"id": job_id, "result": Json(result)},
            )

    def fail(self, job_id: str, error: str, attempts: int, max_attempts: int) -> str:
        """任务失败：还能重试就回队列，否则进死信。返回落定的状态。"""
        status = failure_outcome(attempts, max_attempts)
        with self.store.transaction() as cur:
            if status == QUEUED:
                cur.execute(
                    f"""UPDATE {self.table} SET status = '{QUEUED}', last_error = %(error)s,
                        lease_until = NULL, next_run_at = %(next_run_at)s, updated_at = NOW()
                        WHERE id = %(id)s""",
                    {"id": job_id, "error": error[:2000], "next_run_at": next_run_at(utcnow(), attempts)},
                )
            else:
                cur.execute(
                    f"""UPDATE {self.table} SET status = '{DEAD}', last_error = %(error)s,
                        lease_until = NULL, updated_at = NOW() WHERE id = %(id)s""",
                    {"id": job_id, "error": error[:2000]},
                )
        return status

    def save_checkpoint(self, job_id: str, checkpoint: dict) -> None:
        """写中间态：长任务重启后能从这里接着看，不至于全丢。"""
        with self.store.transaction() as cur:
            cur.execute(
                f"UPDATE {self.table} SET checkpoint = %(checkpoint)s, updated_at = NOW() WHERE id = %(id)s",
                {"id": job_id, "checkpoint": Json(checkpoint)},
            )

    def renew_lease(self, job_id: str, lease_seconds: int = 900) -> None:
        """续租：长任务执行期间别让别的 worker 把任务抢走。"""
        with self.store.transaction() as cur:
            cur.execute(
                f"""UPDATE {self.table} SET lease_until = NOW() + (%(lease_seconds) || ' seconds')::interval,
                    updated_at = NOW() WHERE id = %(id)s""",
                {"id": job_id, "lease_seconds": lease_seconds},
            )

    def cancel(self, job_id: str) -> bool:
        """取消排队中或执行中的任务。"""
        with self.store.transaction() as cur:
            cur.execute(
                f"""UPDATE {self.table} SET status = '{CANCELLED}', lease_until = NULL,
                    updated_at = NOW() WHERE id = %(id)s AND status IN ('{QUEUED}', '{RUNNING}')""",
                {"id": job_id},
            )
            return cur.rowcount > 0

    def replay(self, job_id: str) -> bool:
        """死信重放：回到队列，重置尝试计数。"""
        with self.store.transaction() as cur:
            cur.execute(
                f"""UPDATE {self.table} SET status = '{QUEUED}', attempts = 0,
                    next_run_at = NOW(), last_error = NULL, lease_until = NULL,
                    updated_at = NOW() WHERE id = %(id)s AND status = '{DEAD}'""",
                {"id": job_id},
            )
            return cur.rowcount > 0

    # ---------- 读取 ----------

    def get(self, job_id: str) -> dict | None:
        with self.store.transaction() as cur:
            cur.execute(f"SELECT * FROM {self.table} WHERE id = %s", (job_id,))
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def list(self, *, status: str | None = None, limit: int = 50) -> list[dict]:
        """按状态列出任务；死信列表用它。"""
        with self.store.transaction() as cur:
            if status:
                cur.execute(
                    f"SELECT * FROM {self.table} WHERE status = %s ORDER BY updated_at DESC LIMIT %s",
                    (status, limit),
                )
            else:
                cur.execute(
                    f"SELECT * FROM {self.table} ORDER BY updated_at DESC LIMIT %s", (limit,))
            return [dict(row) for row in cur.fetchall()]

    def stats(self) -> dict:
        """各状态计数，用于界面概览。"""
        with self.store.transaction() as cur:
            cur.execute(f"SELECT status, count(*) AS count FROM {self.table} GROUP BY status")
            counts = {row["status"]: row["count"] for row in cur.fetchall()}
        return {status: counts.get(status, 0)
                for status in (QUEUED, RUNNING, SUCCEEDED, DEAD, CANCELLED)}
