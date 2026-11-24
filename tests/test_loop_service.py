"""自动编码服务测试：记录落库、仓库校验、执行器选择。

执行器本身另有测试；这里用假 worker 验证服务层的编排与留痕。
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.loop_service import LoopService


class Store:
    def __init__(self) -> None:
        self.saved: list[tuple[str, dict]] = []

    def save(self, kind: str, data: dict, record_id=None, version=None) -> dict:
        self.saved.append((kind, data))
        return {"id": "rec1", "version": 1}


class Connection:
    def load(self) -> dict:
        return {"api_key": "k", "base_url": "https://example.test/v1", "model": "fake"}


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "value.txt").write_text("base\n", encoding="utf-8")
    for args in (("init", "-q"), ("config", "user.email", "t@l"), ("config", "user.name", "t"),
                 ("add", "-A"), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return repo


class FakeWorker:
    def __init__(self) -> None:
        self.closed = False

    def attempt(self, context) -> None:  # 测试里由 factory 覆盖
        return None

    def close(self) -> None:
        self.closed = True


def test_records_run_and_returns_summary(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    store = Store()
    service = LoopService(store, Connection())
    worker = FakeWorker()

    def factory(engine, config, worktree, task, log_path=""):
        worker.attempt = lambda ctx: (Path(worktree) / "value.txt").write_text(
            "ok\n", encoding="utf-8")
        return worker

    monkeypatch.setattr(service, "_worker", factory)
    check = ("import pathlib,sys;"
             "sys.exit(0 if pathlib.Path('value.txt').read_text().strip()=='ok' else 1)")
    gate = ["python", "-c", check]
    result = service.run(repo, "把值改成 ok", shlex.join(gate), "model", "patch")
    assert result["status"] == "success"
    assert result["rounds"] == 1
    assert store.saved and store.saved[0][0] == "workflow_run"
    data = store.saved[0][1]
    assert data["kind"] == "loop" and data["status"] == "completed"
    assert data["input"]["task"] == "把值改成 ok"
    assert worker.closed is True


def test_rejects_non_git_directory(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    service = LoopService(Store(), Connection())
    with pytest.raises(DomainError, match="git"):
        service.run(plain, "任务", "true", "model", "patch")


def test_rejects_unknown_engine_and_tier(tmp_path):
    repo = make_repo(tmp_path)
    service = LoopService(Store(), Connection())
    with pytest.raises(DomainError, match="执行器"):
        service.run(repo, "任务", "true", "magic", "patch")
    with pytest.raises(DomainError, match="预算"):
        service.run(repo, "任务", "true", "model", "huge")


def test_rejects_read_only_root(tmp_path):
    repo = make_repo(tmp_path)
    service = LoopService(Store(), Connection())
    with pytest.raises(DomainError, match="写入"):
        service.run(repo, "任务", "true", "model", "patch", writable=False)
