"""队列 worker 与编排服务测试：用假队列，不依赖 PostgreSQL。

要守住的行为：失败要落进队列而不是让 worker 崩、没执行器要进死信、
检查点与续租要真的写出去、领取语句必须带并发保护。
"""

from __future__ import annotations

import pytest

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.task_queue import CANCELLED, DEAD, QUEUED
from rag_tech_retriever.platform.queue_service import QueueService
from rag_tech_retriever.platform.queue_worker import QueueWorker
from rag_tech_retriever.platform.task_queue_store import claim_sql


class FakeQueue:
    """只实现编排层用到的接口，并记录调用。"""

    def __init__(self, job=None) -> None:
        self.job = job
        self.completed = []
        self.cancelled = []
        self.failed = []
        self.checkpoints = []
        self.renewed = []
        self.claims = 0

    def get(self, job_id):
        return self.job

    def save_checkpoint(self, job_id, checkpoint):
        self.checkpoints.append((job_id, checkpoint))

    def renew_lease(self, job_id, lease_seconds=900):
        self.renewed.append((job_id, lease_seconds))

    def complete(self, job_id, result):
        self.completed.append((job_id, result))

    def mark_cancelled(self, job_id, result):
        self.cancelled.append((job_id, result))

    def fail(self, job_id, error, attempts, max_attempts):
        self.failed.append((job_id, error, attempts, max_attempts))
        return DEAD if attempts >= max_attempts else QUEUED

    def claim(self, worker_id, lease_seconds=900):
        self.claims += 1
        return self.job


def make_job(**overrides):
    job = {"id": "job-1", "kind": "team", "status": "running", "attempts": 1,
           "max_attempts": 3, "payload": {"task": "x"}, "checkpoint": None}
    job.update(overrides)
    return job


def test_worker_processes_tasks_up_to_limit():
    calls = []

    class Service:
        def run_once(self, worker_id, lease_seconds=900):
            calls.append((worker_id, lease_seconds))
            return {"id": "job-1", "status": "succeeded"}

    worker = QueueWorker(Service(), worker_id="w-1", poll_seconds=0.2)
    assert worker.run(max_tasks=3) == 3
    assert len(calls) == 3
    assert calls[0][0] == "w-1"


def test_worker_returns_zero_when_queue_empty():
    """空队列时 worker 是常驻等待，不是退出——退出要靠 stop 信号。"""
    class Service:
        def run_once(self, worker_id, lease_seconds=900):
            return None

    worker = QueueWorker(Service(), poll_seconds=0.2)
    worker.stop()
    assert worker.run(max_tasks=2) == 0


def test_worker_survives_task_exception():
    class Service:
        def __init__(self):
            self.calls = 0

        def run_once(self, worker_id, lease_seconds=900):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("数据库抖动")
            return {"id": "job-1", "status": "succeeded"}

    service = Service()
    worker = QueueWorker(service, poll_seconds=0.2)
    assert worker.run(max_tasks=2) == 2  # 第一次异常不算完成，之后两条各算一条
    assert service.calls == 3


def test_worker_stops_on_request():
    class Service:
        def __init__(self):
            self.calls = 0

        def run_once(self, worker_id, lease_seconds=900):
            self.calls += 1
            return {"id": "job-1", "status": "succeeded"}

    service = Service()
    worker = QueueWorker(service, poll_seconds=0.2)

    original = service.run_once

    def stop_after_first(worker_id, lease_seconds=900):
        result = original(worker_id, lease_seconds)
        worker.stop()
        return result

    service.run_once = stop_after_first
    assert worker.run() == 1
    assert service.calls == 1


def test_successful_task_is_completed():
    queue = FakeQueue(make_job())
    service = QueueService(queue)
    service.register("team", lambda job, progress: {"final": "完成"})

    outcome = service.run_claimed(make_job())

    assert outcome["status"] == "succeeded"
    assert queue.completed == [("job-1", {"final": "完成"})]
    assert queue.failed == []


def test_failing_task_goes_back_to_queue_for_retry():
    queue = FakeQueue(make_job())
    service = QueueService(queue)
    service.register("team", lambda job, progress: (_ for _ in ()).throw(RuntimeError("模型超时")))

    outcome = service.run_claimed(make_job())

    assert outcome["status"] == QUEUED
    assert queue.failed and "模型超时" in queue.failed[0][1]
    assert queue.completed == []


def test_task_without_executor_becomes_dead():
    queue = FakeQueue(make_job())
    service = QueueService(queue)

    outcome = service.run_claimed(make_job(kind="loop"))

    assert outcome["status"] == DEAD
    assert queue.failed and "没有可用的执行器" in queue.failed[0][1]


def test_progress_writes_checkpoint_and_renews_lease():
    queue = FakeQueue(make_job())
    service = QueueService(queue)

    def executor(job, progress):
        progress({"round": 1, "passed": False})
        return {"ok": True}

    service.register("team", executor)
    service.run_claimed(make_job())

    assert queue.checkpoints == [("job-1", {"round": 1, "passed": False})]
    assert queue.renewed and queue.renewed[0][0] == "job-1"


def test_cancelled_task_stops_execution():
    queue = FakeQueue(make_job(status=CANCELLED))
    service = QueueService(queue)

    def executor(job, progress):
        progress({"round": 1})
        return {"ok": True}

    service.register("team", executor)
    outcome = service.run_claimed(make_job(status=CANCELLED))

    assert outcome["status"] == CANCELLED
    # 取消的任务不能被当成成功落库：complete() 会把状态写成 succeeded。
    assert queue.cancelled == [("job-1", {"cancelled": True})]
    assert queue.completed == []


def test_claim_statement_guards_concurrency():
    sql = claim_sql("workspace_task_jobs")
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "attempts + 1" in sql
    assert "lease_until" in sql
    # 过期租约的运行中任务也要能被重新领走
    assert "lease_until <= NOW()" in sql


def test_enqueue_rejects_unknown_kind_at_service_level():
    service = QueueService(FakeQueue())
    with pytest.raises(DomainError):
        service.enqueue("unknown", {"a": 1})
