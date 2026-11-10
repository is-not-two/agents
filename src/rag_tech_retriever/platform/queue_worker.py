"""队列 worker：轮询领取任务、执行、回写。

worker 是独立进程（scripts/queue_worker.py 启动），不挂在 Web 请求上：
模型调用与编码循环都是分钟级任务，跟着请求走会随连接断开一起消失。
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rag_tech_retriever.platform.loop_service import build_loop_service
from rag_tech_retriever.platform.queue_service import QueueService
from rag_tech_retriever.platform.team_service import TeamService

LOGGER = logging.getLogger("shilie.queue")


def build_executors(*, store: Any, capabilities: Any, connection: Any,
                    base: Path) -> dict[str, Callable]:
    """构造任务执行器：团队编排与自动编码循环。

    任务载荷来自队列里的 JSON，字段缺失时一律走保守默认值，
    真正的参数校验在入队那一步已经做过一次。
    """

    def team_executor(job: dict, progress: Callable[[dict], None]) -> dict:
        payload = job["payload"]
        progress({"stage": "started", "kind": "team"})
        service = TeamService(store, capabilities, connection)
        result = asyncio.run(service.run(
            list(payload.get("agent_ids") or []),
            str(payload.get("task") or ""),
            str(payload.get("mode") or "group_chat"),
            int(payload.get("max_rounds") or 6),
            bool(payload.get("approved")),
        ))
        progress({"stage": "finished", "kind": "team",
                  "turns": len(result.get("turns") or [])})
        return result

    def loop_executor(job: dict, progress: Callable[[dict], None]) -> dict:
        payload = job["payload"]
        progress({"stage": "started", "kind": "loop"})
        getter = getattr(capabilities, "code", None)
        if getter is None:
            raise RuntimeError("代码工作区未启用")
        target = getter.path_for(str(payload.get("root") or ""))
        service = build_loop_service(store, connection, base)

        def on_progress(info: dict) -> None:
            """每一轮改动统计写进检查点。"""
            progress({"kind": "loop", **info})

        return service.run(
            Path(target["path"]),
            str(payload.get("task") or ""),
            str(payload.get("gate") or ""),
            str(payload.get("engine") or "opencode"),
            str(payload.get("tier") or "patch"),
            target["writable"],
            progress=on_progress,
        )

    return {"team": team_executor, "loop": loop_executor}


class QueueWorker:
    """轮询执行队列里的任务。"""

    def __init__(self, service: QueueService, *, worker_id: str | None = None,
                 poll_seconds: float = 3.0, lease_seconds: int = 900) -> None:
        self.service = service
        self.worker_id = worker_id or f"worker-{os.getpid()}"
        self.poll_seconds = max(0.2, float(poll_seconds))
        self.lease_seconds = max(60, int(lease_seconds))
        self.processed = 0
        self._stop = False

    def stop(self) -> None:
        """请求停止：当前任务跑完这一轮后退出，不打断正在写的代码。"""
        self._stop = True

    def install_signal_handlers(self) -> None:
        """让 systemd 的 SIGTERM 能优雅收尾。"""
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, lambda *_: self.stop())
            except ValueError:
                pass  # 非主线程装不了信号处理器

    def run(self, max_tasks: int | None = None) -> int:
        """持续领取并执行任务；返回处理过的任务数。"""
        LOGGER.info("队列 worker 启动：%s（轮询 %.1fs）", self.worker_id, self.poll_seconds)
        while not self._stop and (max_tasks is None or self.processed < max_tasks):
            try:
                result = self.service.run_once(self.worker_id, self.lease_seconds)
            except Exception:
                LOGGER.exception("worker 循环异常")
                time.sleep(self.poll_seconds)
                continue
            if result is None:
                time.sleep(self.poll_seconds)
                continue
            self.processed += 1
            LOGGER.info("任务处理完毕：%s", result)
        LOGGER.info("队列 worker 退出：共处理 %s 个任务", self.processed)
        return self.processed
