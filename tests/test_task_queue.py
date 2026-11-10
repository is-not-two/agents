"""任务队列纯逻辑测试：状态机、退避、租约与死信判定。"""

from datetime import datetime, timedelta, timezone

import pytest

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.task_queue import (
    BASE_BACKOFF_SECONDS,
    CANCELLED,
    DEAD,
    MAX_BACKOFF_SECONDS,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    backoff_seconds,
    can_cancel,
    describe,
    failure_outcome,
    is_terminal,
    lease_expired,
    next_run_at,
    validate_enqueue,
)

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def test_enqueue_accepts_known_kind():
    payload = {"root": "demo", "task": "修复空指针", "gate": "pytest -q"}
    result = validate_enqueue("loop", payload, max_attempts=2, priority=10)
    assert result == {"kind": "loop", "payload": payload,
                      "max_attempts": 2, "priority": 10}


@pytest.mark.parametrize("kind", ["", "unknown", None, 7])
def test_enqueue_rejects_unknown_kind(kind):
    with pytest.raises(DomainError):
        validate_enqueue(kind, {"task": "x"})


@pytest.mark.parametrize("payload", [None, {}, [], "x", 3])
def test_enqueue_rejects_empty_payload(payload):
    with pytest.raises(DomainError):
        validate_enqueue("loop", payload)


@pytest.mark.parametrize("attempts", [0, -1, 11, True, "3"])
def test_enqueue_rejects_bad_max_attempts(attempts):
    with pytest.raises(DomainError):
        validate_enqueue("loop", {"task": "x"}, max_attempts=attempts)


@pytest.mark.parametrize("priority", [-1, 101, True, "5"])
def test_enqueue_rejects_bad_priority(priority):
    with pytest.raises(DomainError):
        validate_enqueue("loop", {"task": "x"}, priority=priority)


def test_backoff_grows_and_caps():
    assert backoff_seconds(1) == BASE_BACKOFF_SECONDS
    assert backoff_seconds(2) == BASE_BACKOFF_SECONDS * 2
    assert backoff_seconds(3) == BASE_BACKOFF_SECONDS * 4
    assert backoff_seconds(20) == MAX_BACKOFF_SECONDS
    assert backoff_seconds(0) == BASE_BACKOFF_SECONDS


def test_failure_goes_back_to_queue_until_attempts_exhausted():
    assert failure_outcome(1, 3) == QUEUED
    assert failure_outcome(2, 3) == QUEUED
    assert failure_outcome(3, 3) == DEAD
    assert failure_outcome(4, 3) == DEAD


def test_next_run_at_pushes_by_backoff():
    assert next_run_at(NOW, 1) == NOW + timedelta(seconds=BASE_BACKOFF_SECONDS)
    assert next_run_at(NOW, 2) == NOW + timedelta(seconds=BASE_BACKOFF_SECONDS * 2)


def test_expired_lease_can_be_reclaimed():
    expired = {"status": RUNNING, "lease_until": NOW - timedelta(seconds=1)}
    alive = {"status": RUNNING, "lease_until": NOW + timedelta(seconds=60)}
    assert lease_expired(expired, NOW) is True
    assert lease_expired(alive, NOW) is False


def test_missing_lease_counts_as_expired():
    assert lease_expired({"status": RUNNING}, NOW) is True


def test_only_running_jobs_can_have_expired_lease():
    assert lease_expired({"status": QUEUED, "lease_until": NOW - timedelta(days=1)}, NOW) is False
    assert lease_expired({"status": SUCCEEDED, "lease_until": NOW - timedelta(days=1)}, NOW) is False


def test_terminal_statuses():
    assert is_terminal(SUCCEEDED) and is_terminal(DEAD) and is_terminal(CANCELLED)
    assert not is_terminal(QUEUED) and not is_terminal(RUNNING)


def test_cancel_allowed_only_for_active_jobs():
    assert can_cancel({"status": QUEUED}) is True
    assert can_cancel({"status": RUNNING}) is True
    assert can_cancel({"status": SUCCEEDED}) is False
    assert can_cancel({"status": DEAD}) is False


def test_describe_hides_payload_and_formats_time():
    view = describe({
        "id": "job-1", "kind": "loop", "status": QUEUED, "priority": 5,
        "attempts": 1, "max_attempts": 3, "payload": {"secret": "x"},
        "next_run_at": NOW, "created_at": NOW, "updated_at": NOW, "last_error": "",
    })
    assert view["id"] == "job-1"
    assert view["next_run_at"] == NOW.isoformat()
    assert view["last_error"] == ""
    assert "payload" not in view


# ---------- 入队载荷校验 ----------

VALID_LOOP = {"root": "demo", "task": "修复求和", "gate": "pytest -q",
               "engine": "opencode", "tier": "patch"}
VALID_TEAM = {"task": "评估候选人", "agent_ids": ["a1"], "mode": "group_chat"}


def test_valid_loop_payload_is_accepted():
    spec = validate_enqueue("loop", dict(VALID_LOOP))
    assert spec["kind"] == "loop"


def test_valid_team_payload_is_accepted():
    spec = validate_enqueue("team", dict(VALID_TEAM))
    assert spec["kind"] == "team"


@pytest.mark.parametrize("missing", ["root", "task", "gate"])
def test_loop_payload_requires_core_fields(missing):
    payload = dict(VALID_LOOP)
    payload.pop(missing)
    with pytest.raises(DomainError):
        validate_enqueue("loop", payload)


def test_loop_payload_rejects_unknown_engine_and_tier():
    bad_engine = {**VALID_LOOP, "engine": "vim"}
    with pytest.raises(DomainError):
        validate_enqueue("loop", bad_engine)
    bad_tier = {**VALID_LOOP, "tier": "huge"}
    with pytest.raises(DomainError):
        validate_enqueue("loop", bad_tier)


def test_loop_payload_rejects_blank_text():
    with pytest.raises(DomainError):
        validate_enqueue("loop", {**VALID_LOOP, "gate": "   "})


def test_team_payload_requires_members():
    with pytest.raises(DomainError):
        validate_enqueue("team", {"task": "评估候选人", "agent_ids": []})
    with pytest.raises(DomainError):
        validate_enqueue("team", {"task": "评估候选人"})


def test_team_payload_rejects_too_many_members():
    with pytest.raises(DomainError):
        validate_enqueue("team", {**VALID_TEAM, "agent_ids": ["a", "b", "c", "d", "e"]})


def test_team_payload_rejects_unknown_mode():
    with pytest.raises(DomainError):
        validate_enqueue("team", {**VALID_TEAM, "mode": "committee"})
