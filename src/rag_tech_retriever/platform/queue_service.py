"""任务队列编排：入队、领取、执行、回写与死信处理。

这一层只做调度，不认识具体任务；每种任务怎么跑由调用方注册执行器，
执行器签名是 `executor(job, progress) -> dict`，其中 progress 用于写检查点。
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.task_queue import (
    CANCELLED,
    DEAD,
    QUEUED,
    describe,
    is_terminal,
    validate_enqueue,
)
from rag_tech_retriever.platform.task_queue_store import TaskQueueStore

Executor = Callable[[dict, Callable[[dict], None]], dict]


class QueueCancelled(Exception):
    """任务在执行途中被取消。"""


class QueueService:
    """队列编排服务；执行器按任务类型注册。"""

    def __init__(self, queue: TaskQueueStore) -> None:
        self.queue = queue
        self.executors: dict[str, Executor] = {}

    def register(self, kind: str, executor: Executor) -> None:
        """注册任务执行器；同类型重复注册会覆盖旧实现。"""
        self.executors[kind] = executor

    # ---------- 入队 ----------

    def enqueue(self, kind: str, payload: dict, *, max_attempts: int = 3, priority: int = 50,
                idempotency_key: str | None = None) -> dict:
        """校验并入队，返回任务视图。"""
        spec = validate_enqueue(kind, payload, max_attempts=max_attempts, priority=priority)
        job_id = uuid4().hex
        job = self.queue.enqueue(job_id, spec["kind"], spec["payload"],
                                 max_attempts=spec["max_attempts"], priority=spec["priority"],
                                 idempotency_key=idempotency_key)
        return describe(job)

    # ---------- 查询与操作 ----------

    def status(self, job_id: str) -> dict:
        """任务视图；找不到时给出可展示的错误。"""
        job = self.queue.get(job_id)
        if job is None:
            raise DomainError("任务不存在")
        return describe(job)

    def detail(self, job_id: str) -> dict:
        """任务详情：含载荷、结果与检查点。"""
        job = self.queue.get(job_id)
        if job is None:
            raise DomainError("任务不存在")
        view = describe(job)
        view["payload"] = job.get("payload") or {}
        view["result"] = job.get("result")
        view["checkpoint"] = job.get("checkpoint")
        return view

    def cancel(self, job_id: str) -> dict:
        """取消任务；已结束的任务不受理。"""
        if not self.queue.cancel(job_id):
            current = self.queue.get(job_id)
            if current is None:
                raise DomainError("任务不存在")
            raise DomainError(f"任务已处于 {current['status']}，无法取消")
        return self.status(job_id)

    def replay(self, job_id: str) -> dict:
        """死信重放。"""
        if not self.queue.replay(job_id):
            current = self.queue.get(job_id)
            if current is None:
                raise DomainError("任务不存在")
            raise DomainError(f"只有死信任务能重放，当前为 {current['status']}")
        return self.status(job_id)

    def list_jobs(self, *, status: str | None = None, limit: int = 50) -> list[dict]:
        return [describe(job) for job in self.queue.list(status=status, limit=limit)]

    def stats(self) -> dict:
        return self.queue.stats()

    # ---------- 执行 ----------

    def claim(self, worker_id: str, lease_seconds: int = 900) -> dict | None:
        """领取一条就绪任务。"""
        return self.queue.claim(worker_id, lease_seconds)

    def run_claimed(self, job: dict, lease_seconds: int = 900) -> dict:
        """执行一条已领取的任务，并把结果或失败写回队列。"""
        executor = self.executors.get(job["kind"])
        if executor is None:
            self.queue.fail(job["id"], f"没有可用的执行器：{job['kind']}",
                            job["attempts"], job["max_attempts"])
            return {"id": job["id"], "status": DEAD, "reason": "缺少执行器"}

        def progress(checkpoint: dict) -> None:
            """写中间态并续租；同时看一眼任务是否已被取消。"""
            current = self.queue.get(job["id"])
            if current is not None and current.get("status") == CANCELLED:
                raise QueueCancelled("任务已取消")
            self.queue.save_checkpoint(job["id"], checkpoint)
            self.queue.renew_lease(job["id"], lease_seconds)

        try:
            result = executor(job, progress)
        except QueueCancelled:
            self.queue.complete(job["id"], {"cancelled": True})
            return {"id": job["id"], "status": CANCELLED}
        except Exception as exc:  # noqa: BLE001 - 失败要落进队列，不能让 worker 崩掉
            message = f"{type(exc).__name__}: {exc}"
            status = self.queue.fail(job["id"], message, job["attempts"], job["max_attempts"])
            return {"id": job["id"], "status": status, "error": message[:300]}
        self.queue.complete(job["id"], result if isinstance(result, dict) else {"output": result})
        return {"id": job["id"], "status": "succeeded"}

    def run_once(self, worker_id: str, lease_seconds: int = 900) -> dict | None:
        """领取并执行一条任务；队列为空时返回 None。"""
        job = self.claim(worker_id, lease_seconds)
        if job is None:
            return None
        return self.run_claimed(job, lease_seconds)


def pending_jobs(queue: TaskQueueStore) -> list[dict]:
    """仍在队列里、可以继续跑的任务（用于巡检）。"""
    return [job for job in queue.list(status=QUEUED, limit=100)
            if not is_terminal(job.get("status"))]
