"""Fake process integration: no scheduled model calls or edits to operational state."""

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[2] / ".codex/agents-autopilot/runner.py"


@pytest.fixture
def runner(tmp_path, monkeypatch):
    if sys.platform != "win32" or not RUNNER.is_file():
        pytest.skip("Windows Task Scheduler runner is local to this workspace")
    spec = importlib.util.spec_from_file_location("qa_autopilot_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (tmp_path / "prompt.txt").write_text("fake executor", encoding="utf-8")
    module.ROOT = tmp_path
    module.CONFIG = {**module.CONFIG, "workspace": str(workspace), "poll_seconds": 0.001}
    module.binary = lambda: Path("fake-codex.exe")
    module.quota = lambda: {"allowed": True, "weekly_remaining_percent": 80}
    yield module, workspace, tmp_path, monkeypatch


def launch(runner, result=None, code=0, changed=False):
    module, workspace, root, monkeypatch = runner
    calls = []

    class Process:
        returncode = code

        def __init__(self, args, **kwargs):
            self.stdin = io.StringIO()
            calls.append(args)
            if changed:
                (workspace / "src/new.py").write_text("# fake modification")
            if result is not None:
                path = Path(args[args.index("--output-last-message") + 1])
                path.write_text(json.dumps(result), encoding="utf-8")

        def poll(self):
            return self.returncode

    monkeypatch.setattr(module.subprocess, "Popen", Process)
    module.run()
    return json.loads((root / "last-run.json").read_text(encoding="utf-8")), calls


def contract(status, changes=None):
    return {"status": status, "summary": "fake only", "changes": changes or [],
            "verification": ["fake check: passed"], "rollback_ids": ["fake-stage"], "reasons": []}


@pytest.mark.parametrize("status", ["blocked", "failed", "checked_no_changes", "completed_changes"])
def test_declared_outcome_is_checked_not_replaced_by_exit_zero(runner, status):
    changes = ["src/new.py"] if status == "completed_changes" else []
    state, calls = launch(runner, contract(status, changes), changed=bool(changes))
    assert state["status"] == status
    assert state["contract_version"] == 1
    assert "--output-schema" in calls[0]
    assert runner[0].CONFIG["model"] == "gpt-6.1-sol"
    assert runner[0].CONFIG["reasoning_effort"] == "xhigh"


def test_stale_result_is_cleared_before_executor(runner):
    root = runner[2]
    (root / "last-result.json").write_text(json.dumps(contract("checked_no_changes")))
    state, _ = launch(runner)
    assert state["status"] == "failed_contract"


def test_nonzero_executor_and_inconsistent_change_manifest(runner):
    state, _ = launch(runner, contract("checked_no_changes"), code=2)
    assert state["status"] == "failed_execution"
    state, _ = launch(runner, contract("checked_no_changes"), changed=True)
    assert state["status"] == "failed_contract"


@pytest.mark.parametrize("unavailable", [False, True])
def test_quota_preflight_skips_without_launching_executor(runner, unavailable):
    module = runner[0]

    def quota():
        if unavailable:
            raise RuntimeError("fake unavailable")
        return {"allowed": False, "weekly_remaining_percent": 5}

    module.quota = quota
    state, calls = launch(runner)
    assert calls == []
    assert state["status"] == ("skipped_quota_unavailable" if unavailable else "skipped_quota")


@pytest.mark.parametrize("used,allowed", [(94, True), (95, False), (100, False)])
def test_weekly_threshold_is_strict(runner, used, allowed):
    module = runner[0]
    result = module.evaluate_quota({"rateLimits": {"secondary": {
        "windowDurationMins": 10080, "usedPercent": used,
    }}})
    assert result["allowed"] is allowed


@pytest.mark.parametrize("used", [-1, 101, float("nan"), float("inf"), True, None])
def test_invalid_quota_is_never_assumed_available(runner, used):
    with pytest.raises(RuntimeError):
        runner[0].evaluate_quota({"rateLimits": {"secondary": {
            "windowDurationMins": 10080, "usedPercent": used,
        }}})


def test_legacy_audit_keeps_original_status_and_is_idempotent(runner):
    module, _, root, _ = runner
    (root / "last-run.json").write_text(json.dumps({"status": "completed", "at": "test-time"}))
    result = module.audit_last_run()
    assert result["status"] == "unverified_legacy"
    assert result["previous_status"] == "completed"
    assert result["previous_at"] == "test-time"
    assert module.audit_last_run() == result


def test_active_run_lock_prevents_audit_and_second_run(runner):
    module, _, root, _ = runner
    state_path = root / "last-run.json"
    state_path.write_text(json.dumps({"status": "running"}))
    with (root / "run.lock").open("w+b") as lock:
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        module.msvcrt.locking(lock.fileno(), module.msvcrt.LK_NBLCK, 1)
        try:
            assert module.audit_last_run()["status"] == "audit_busy"
            module.run()
            assert json.loads(state_path.read_text())["status"] == "running"
        finally:
            lock.seek(0)
            module.msvcrt.locking(lock.fileno(), module.msvcrt.LK_UNLCK, 1)


@pytest.mark.parametrize("reason", ["quota", "quota_unavailable", "time_limit"])
def test_running_executor_is_stopped_with_distinct_reason(runner, reason):
    module, _, root, monkeypatch = runner
    checks = 0
    stopped = []

    def quota():
        nonlocal checks
        checks += 1
        if checks == 1:
            return {"allowed": True}
        if reason == "quota_unavailable":
            raise RuntimeError("fake unavailable")
        return {"allowed": False}

    class Process:
        stdin = io.StringIO()
        returncode = None

        def __init__(self, *args, **kwargs):
            pass

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            raise module.subprocess.TimeoutExpired("fake executor", timeout)

    def stop(process):
        process.returncode = 1
        stopped.append(True)

    module.quota = quota
    module.stop = stop
    if reason == "time_limit":
        module.CONFIG["max_run_seconds"] = 0
    monkeypatch.setattr(module.subprocess, "Popen", Process)
    module.run()
    assert stopped == [True]
    assert json.loads((root / "last-run.json").read_text())["status"] == "stopped_" + reason
