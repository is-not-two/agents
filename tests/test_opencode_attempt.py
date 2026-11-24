"""OpenCode 执行器测试：请求拼装、只读校验、服务复用。

不真的连服务：opener 注入假实现，验证我们这层的协议是否正确。
真实链路已在服务器上跑过（serve + /session/{id}/message）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_tech_retriever.platform.opencode_attempt import OpenCodeAttempt, OpenCodeError

CONFIG = {"model": "mimo-v2.6-flash", "base_url": "https://example.test/v1", "api_key": "k"}


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    return root


class Recorder:
    def __init__(self, reply: str = "已改好", cwd: str = "") -> None:
        self.calls: list[tuple[str, str]] = []
        self.reply, self.cwd = reply, cwd

    def __call__(self, url, method="GET", payload=None):
        self.calls.append((method, url))
        if url.endswith("/doc"):
            return {"openapi": "3.1.0"}
        if url.endswith("/session"):
            return {"id": "ses_1"}
        if url.endswith("/prompt_async"):
            return {}
        if url.endswith("/session/status"):
            return {}
        if url.endswith("/session/ses_1/message"):
            info = {"role": "assistant", "time": {"completed": 1}}
            if self.cwd:
                info["path"] = {"cwd": self.cwd}
            return [{"info": info, "parts": [{"type": "text", "text": self.reply}]}]
        raise AssertionError(url)


def test_prompt_carries_feedback_and_readonly(tmp_path):
    attempt = OpenCodeAttempt(CONFIG, make_root(tmp_path), "修好加法",
                              readonly=["tests"], base_url="http://127.0.0.1:4096")
    text = attempt.prompt("AssertionError: 期望 5")
    assert "修好加法" in text and "AssertionError" in text
    assert "tests" in text


def test_attempt_posts_session_then_message(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    recorder = Recorder()
    attempt = OpenCodeAttempt(CONFIG, root, "任务", base_url="http://127.0.0.1:4096",
                              opener=recorder)
    monkeypatch.setattr(attempt, "_touched_readonly", list)
    context = type("Ctx", (), {"feedback": "", "tried": [], "round_no": 1})()
    attempt.attempt(context)
    tail = [call[1].split("4096")[-1] for call in recorder.calls]
    assert tail[0] == "/doc" and tail[1] == "/session"
    assert "/session/ses_1/prompt_async" in tail
    assert any(item.endswith("/session/ses_1/message") for item in tail)
    assert context.tried and context.tried[0] == "已改好"


def test_readonly_touch_fails_round(tmp_path):
    attempt = OpenCodeAttempt(CONFIG, make_root(tmp_path), "任务", readonly=["tests"],
                              base_url="http://127.0.0.1:4096", opener=Recorder())
    attempt._touched_readonly = lambda: ["tests/check.py"]  # type: ignore[method-assign]
    context = type("Ctx", (), {"feedback": "", "tried": [], "round_no": 1})()
    with pytest.raises(OpenCodeError, match="只读路径"):
        attempt.attempt(context)


def test_existing_server_is_reused(tmp_path):
    recorder = Recorder()
    attempt = OpenCodeAttempt(CONFIG, make_root(tmp_path), "任务",
                              base_url="http://127.0.0.1:4096", opener=recorder)
    assert attempt.ensure_server() == "http://127.0.0.1:4096"
    assert recorder.calls == [("GET", "http://127.0.0.1:4096/doc")]


def test_reply_from_wrong_directory_is_rejected(tmp_path):
    """服务复用到别的目录时，改动会写错地方；必须整轮失败而不是当作成功。"""
    root = make_root(tmp_path)

    recorder = Recorder(reply="改好了", cwd=str(tmp_path / "somewhere-else"))
    attempt = OpenCodeAttempt(CONFIG, root, "任务", base_url="http://127.0.0.1:4096",
                              opener=recorder)
    attempt._touched_readonly = list
    context = type("Ctx", (), {"feedback": "", "tried": [], "round_no": 1})()
    with pytest.raises(OpenCodeError, match="工作目录"):
        attempt.attempt(context)
