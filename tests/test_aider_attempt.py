"""Aider 执行器测试：命令参数、环境变量、失败处理。

不真的调用 aider：runner 注入假实现，只验证我们这层拼装是否正确。
真实链路已在服务器上跑过一次（两文件一致性修复）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rag_tech_retriever.platform.aider_attempt import AiderAttempt

CONFIG = {"api_key": "sk-test", "base_url": "https://example.test/v1", "model": "mimo-v2.6-flash"}


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "b.py").write_text("y = 2\n", encoding="utf-8")
    return root


def test_command_carries_required_flags(tmp_path):
    attempt = AiderAttempt(CONFIG, make_root(tmp_path), "修好加法", files=["a.py", "b.py"])
    command = attempt.command("AssertionError: 期望 5")
    assert "--no-auto-commits" in command  # 否则绿点语义被 aider 自己的提交打乱
    assert "--no-stream" in command
    assert command[command.index("--model") + 1] == "openai/mimo-v2.6-flash"
    message = command[command.index("--message") + 1]
    assert "修好加法" in message and "AssertionError" in message
    assert command[-2:] == ["a.py", "b.py"]
    # aider 默认会把自己的缓存写进 .gitignore 与仓库根，必须关掉，免得混进绿点。
    assert "--no-add-gitignore-files" in command
    assert any("shilie-aider" in item for item in command)


def test_environment_holds_key_only_in_process(tmp_path):
    attempt = AiderAttempt(CONFIG, make_root(tmp_path), "任务")
    env = attempt.environment()
    assert env["OPENAI_API_KEY"] == "sk-test"
    assert env["OPENAI_API_BASE"] == "https://example.test/v1"


def test_default_files_skip_caches(tmp_path):
    root = make_root(tmp_path)
    (root / "__pycache__").mkdir()
    (root / "__pycache__/x.pyc").write_bytes(b"\x00")
    files = AiderAttempt(CONFIG, root, "任务")._default_files()
    assert files == ["a.py", "b.py"]


def test_nonzero_exit_becomes_round_failure(tmp_path):
    def runner(*args, **kwargs):
        assert kwargs["stdin"] is subprocess.DEVNULL  # 否则 aider 会等输入
        return subprocess.CompletedProcess(args, 1, "", "model not found")

    attempt = AiderAttempt(CONFIG, make_root(tmp_path), "任务", runner=runner)
    context = type("Ctx", (), {"feedback": "", "tried": [], "round_no": 1})()
    with pytest.raises(RuntimeError, match="aider 执行失败"):
        attempt.attempt(context)


def test_success_records_short_summary(tmp_path):
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "Applied edit to a.py\nTokens: 12", "")

    attempt = AiderAttempt(CONFIG, make_root(tmp_path), "任务", runner=runner)
    context = type("Ctx", (), {"feedback": "", "tried": [], "round_no": 1})()
    attempt.attempt(context)
    assert context.tried and "Applied edit" in context.tried[0]


def test_readonly_paths_are_not_offered(tmp_path):
    root = make_root(tmp_path)
    (root / "tests").mkdir()
    (root / "tests/check.py").write_text("assert True\n", encoding="utf-8")
    files = AiderAttempt(CONFIG, root, "任务", readonly=["tests"])._default_files()
    assert files == ["a.py", "b.py"]


def test_touching_readonly_path_fails_the_round(tmp_path):
    root = make_root(tmp_path)
    (root / "tests").mkdir()
    (root / "tests/check.py").write_text("assert True\n", encoding="utf-8")

    def runner(command, **kwargs):
        if command[0] == "git":
            return subprocess.CompletedProcess(command, 0, " M tests/check.py\n", "")
        (root / "tests/check.py").write_text("pass\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "Applied edit", "")

    attempt = AiderAttempt(CONFIG, root, "任务", readonly=["tests"], runner=runner)
    context = type("Ctx", (), {"feedback": "", "tried": [], "round_no": 1})()
    with pytest.raises(RuntimeError, match="只读路径"):
        attempt.attempt(context)
