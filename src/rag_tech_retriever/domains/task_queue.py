"""任务队列契约：状态机、退避、租约与死信判定。

只回答「这个任务现在该处于什么状态、下一次什么时候可以再跑」，
不碰 PostgreSQL，也不做 HTTP。真正的读写在 platform/task_queue_store.py，
编排与执行在 platform/queue_service.py 与 platform/queue_worker.py。

为什么要有队列：模型调用与编码循环都是分钟级任务，放在请求里同步跑，
一断线就全丢；排队执行才能做到无人值守、失败重试与死信兜底。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from rag_tech_retriever.domains.life_planning import DomainError

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
DEAD = "dead"
CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset({SUCCEEDED, DEAD, CANCELLED})
KNOWN_KINDS = ("team", "loop")

# 执行器与档位的合法取值。放在 domain 层是为了让入队校验有唯一事实源：
# platform/loop_service.py 从这里导入，两边不会各写一份。
LOOP_ENGINES = ("opencode", "aider", "model")
LOOP_TIERS = ("patch", "feature", "epic")

# 团队成员上限，与 platform/team_service.py 的 MAX_TEAM_SIZE 一致。
MAX_TEAM_MEMBERS = 4

MAX_ATTEMPTS_LIMIT = 10
BASE_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 300
DEFAULT_LEASE_SECONDS = 900


def utcnow() -> datetime:
    """统一用带时区的时间；库里存 timestamptz，比较时不能混用裸 datetime。"""
    return datetime.now(timezone.utc)


def validate_enqueue(kind: str, payload: Any, *, max_attempts: int = 3,
                     priority: int = 0) -> dict:
    """校验入队参数：只接受已知任务类型与非空载荷。"""
    if kind not in KNOWN_KINDS:
        raise DomainError(f"未知任务类型：{kind}")
    if not isinstance(payload, dict) or not payload:
        raise DomainError("任务载荷不能为空")
    if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_ATTEMPTS_LIMIT:
        raise DomainError(f"最大尝试次数必须是 1–{MAX_ATTEMPTS_LIMIT} 的整数")
    if type(priority) is not int or not 0 <= priority <= 100:
        raise DomainError("优先级必须是 0–100 的整数")
    _validate_payload(kind, payload)
    return {"kind": kind, "payload": payload, "max_attempts": max_attempts, "priority": priority}


def _require_text(payload: dict, key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DomainError(f"{label}不能为空")
    return value.strip()


def _validate_payload(kind: str, payload: dict) -> None:
    """按任务类型校验载荷字段；缺失或非法一律当场拒绝。"""
    if kind == "loop":
        _require_text(payload, "root", "代码仓库")
        _require_text(payload, "task", "改动目标")
        _require_text(payload, "gate", "门禁命令")
        engine = payload.get("engine", "opencode")
        if engine not in LOOP_ENGINES:
            raise DomainError(f"不支持的执行器：{engine}")
        tier = payload.get("tier", "patch")
        if tier not in LOOP_TIERS:
            raise DomainError(f"不支持的预算档位：{tier}")
        return
    if kind == "team":
        _require_text(payload, "task", "团队目标")
        members = payload.get("agent_ids")
        if not isinstance(members, list) or not members:
            raise DomainError("团队成员不能为空")
        if len(members) > MAX_TEAM_MEMBERS:
            raise DomainError(f"团队成员最多 {MAX_TEAM_MEMBERS} 个")
        mode = payload.get("mode", "group_chat")
        if mode not in ("group_chat", "magentic"):
            raise DomainError(f"不支持的协作方式：{mode}")


def backoff_seconds(attempts: int) -> int:
    """指数退避：第 n 次失败后等 base * 2^(n-1) 秒，封顶 5 分钟。"""
    attempts = max(attempts, 1)
    return min(BASE_BACKOFF_SECONDS * (2 ** (attempts - 1)), MAX_BACKOFF_SECONDS)


def failure_outcome(attempts: int, max_attempts: int) -> str:
    """失败之后是回队列重试，还是直接进死信等人处理。"""
    return DEAD if attempts >= max_attempts else QUEUED


def next_run_at(now: datetime, attempts: int) -> datetime:
    """下一次可执行时刻。"""
    return now + timedelta(seconds=backoff_seconds(attempts))


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def lease_expired(job: dict, now: datetime | None = None) -> bool:
    """租约过期的 running 任务可以重新领取：worker 崩了不能让任务永远卡住。"""
    if job.get("status") != RUNNING:
        return False
    lease = _as_utc(job.get("lease_until"))
    if lease is None:
        return True
    return lease <= (now or utcnow())


def is_terminal(status: str) -> bool:
    """终态任务不再参与领取。"""
    return status in TERMINAL_STATUSES


def can_cancel(job: dict) -> bool:
    """只有排队中与执行中的任务能取消。"""
    return job.get("status") in {QUEUED, RUNNING}


def describe(job: dict) -> dict:
    """给界面用的精简视图，不含载荷与结果正文。"""
    def stamp(key: str) -> str:
        value = _as_utc(job.get(key))
        return value.isoformat() if value else ""

    return {
        "id": job.get("id"),
        "kind": job.get("kind"),
        "status": job.get("status"),
        "priority": job.get("priority"),
        "attempts": job.get("attempts"),
        "max_attempts": job.get("max_attempts"),
        "next_run_at": stamp("next_run_at"),
        "last_error": job.get("last_error") or "",
        "created_at": stamp("created_at"),
        "updated_at": stamp("updated_at"),
    }
