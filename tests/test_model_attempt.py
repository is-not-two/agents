"""模型写入器测试：解析容错、路径边界、只读拦截、与循环的异常配合。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_tech_retriever.platform.coding_loop import Budget, CodingLoop
from rag_tech_retriever.platform.model_attempt import Edit, EditingModel

CONFIG = {"api_key": "k", "base_url": "https://example.test/v1", "model": "fake"}


def fake_post(payload: str):
    def post(config, body, timeout, max_chars):
        return {"choices": [{"message": {"content": payload}}]}

    return post


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    (root / "tests/test_app.py").write_text("def test(): assert True\n", encoding="utf-8")
    return root


def _init_git(repo: Path) -> None:
    import subprocess

    for args in (("init", "-q"), ("config", "user.email", "t@local"),
                 ("config", "user.name", "t"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_parse_plain_and_fenced_json(tmp_path):
    model = EditingModel(CONFIG, make_root(tmp_path), "任务")
    plain = json.dumps({"edits": [{"path": "a.py", "content": "y = 2\n"}], "note": "改"},
                       ensure_ascii=False)
    edits, note = model.parse(plain)
    assert edits == [Edit("a.py", "y = 2\n")] and note == "改"
    fenced = f"说明文字\n```json\n{plain}\n```\n"
    assert model.parse(fenced)[0] == [Edit("a.py", "y = 2\n")]
    assert model.parse("完全不是 JSON") == ([], "")


def test_apply_writes_and_rejects_unsafe_paths(tmp_path):
    root = make_root(tmp_path)
    model = EditingModel(CONFIG, root, "任务", readonly=["tests"])
    applied = model.apply([Edit("new/mod.py", "print(1)\n")])
    assert applied == ["new/mod.py"]
    assert (root / "new/mod.py").read_text(encoding="utf-8") == "print(1)\n"
    for bad in ("../escape.py", "/abs.py", "tests/test_app.py", ".env"):
        with pytest.raises(ValueError):
            model.apply([Edit(bad, "x")])


def test_attempt_sends_failure_feedback_and_applies(tmp_path):
    root = make_root(tmp_path)
    payload = json.dumps({"edits": [{"path": "app.py", "content": "x = 2\n"}], "note": "改成 2"})
    seen: list[str] = []

    def post(config, body, timeout, max_chars):
        seen.append(body["messages"][-1]["content"])
        return {"choices": [{"message": {"content": payload}}]}

    model = EditingModel(CONFIG, root, "把 x 改成 2", post=post)
    context = type("Ctx", (), {"feedback": "AssertionError: 期望 2", "tried": [], "round_no": 1})()
    model.attempt(context)
    assert (root / "app.py").read_text(encoding="utf-8") == "x = 2\n"
    assert "AssertionError" in seen[0]
    assert context.tried and "改成 2" in context.tried[0]


def test_attempt_without_edits_raises(tmp_path):
    model = EditingModel(CONFIG, make_root(tmp_path), "任务", post=fake_post("我不知道"))
    context = type("Ctx", (), {"feedback": "", "tried": [], "round_no": 1})()
    with pytest.raises(RuntimeError):
        model.attempt(context)


def test_loop_survives_attempt_exception(tmp_path):
    repo = make_root(tmp_path)
    _init_git(repo)
    loop = CodingLoop(repo, tmp_path / "wt", ["python", "-c", "raise SystemExit(1)"],
                      Budget(rounds=3, max_files=5, max_lines=50, minutes=5))
    try:
        def broken(ctx):
            raise RuntimeError("模型没输出")

        result = loop.run(broken)
    finally:
        loop.close()
    assert result.status == "stuck"
    assert all(item.signature == "error" for item in result.attempts)


def test_apply_rejects_more_files_than_limit(tmp_path):
    root = make_root(tmp_path)
    model = EditingModel(CONFIG, root, "任务", max_files=2)
    edits = [Edit(f"f{index}.py", "x = 1\n") for index in range(3)]
    with pytest.raises(ValueError, match="超过上限"):
        model.apply(edits)
