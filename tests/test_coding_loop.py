"""编码循环测试：绿点、回退、换方向、预算与续期。

全部用真实 git 仓库与真实 worktree（不 mock git），因为这套逻辑的价值就在状态正确。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from rag_tech_retriever.platform import coding_loop
from rag_tech_retriever.platform.coding_loop import Budget, CodingLoop


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@local")
    git(repo, "config", "user.name", "t")
    (repo / "value.txt").write_text("base\n", encoding="utf-8")
    (repo / "notes.txt").write_text("keep\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def gate_is(expected: str, notes: str = "keep") -> list[str]:
    """校验：value.txt 等于期望值，且 notes.txt 保持原样；失败时打印原因供循环回传。"""
    code = (
        "import pathlib,sys,json;"
        f"expected={json.dumps(expected)};wanted={json.dumps(notes)};"
        "v=pathlib.Path('value.txt').read_text(encoding='utf-8').strip();"
        "n=pathlib.Path('notes.txt').read_text(encoding='utf-8').strip();"
        "ok=v==expected and n==wanted;"
        "print('校验失败：value=%r notes=%r' % (v, n)) if not ok else None;"
        "sys.exit(0 if ok else 1)"
    )
    return [sys.executable, "-c", code]


def test_budget_tiers_and_renew_caps():
    budget = Budget.tier("epic")
    assert (budget.rounds, budget.max_files, budget.max_lines) == (60, 30, 3000)
    assert budget.renew() and budget.rounds == 90
    assert budget.renew() and budget.rounds == 135
    assert budget.renew() and budget.rounds == 202
    assert budget.renew() is False
    with pytest.raises(ValueError):
        Budget.tier("huge")


def test_success_on_first_passing_attempt(tmp_path):
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", gate_is("ok"),
                      Budget(rounds=5, max_files=5, max_lines=50, minutes=5))
    try:
        def attempt(ctx):
            (loop.worktree / "value.txt").write_text("ok\n", encoding="utf-8")

        result = loop.run(attempt)
    finally:
        loop.close()
    assert result.status == "success"
    assert result.rounds == 1
    assert len(result.green_points) == 2  # 基线 + 成功点
    assert result.green_points[-1].commit != result.green_points[0].commit


def test_failure_rolls_back_and_feeds_reason(tmp_path):
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", gate_is("ok"),
                      Budget(rounds=4, max_files=5, max_lines=50, minutes=5))
    seen: list[str] = []

    try:
        def attempt(ctx):
            seen.append(ctx.feedback)
            if len(seen) < 3:
                (loop.worktree / "value.txt").write_text(f"bad{len(seen)}\n", encoding="utf-8")
            else:
                (loop.worktree / "value.txt").write_text("ok\n", encoding="utf-8")

        result = loop.run(attempt)
        submitted = (loop.worktree / "value.txt").read_text(encoding="utf-8").strip()
    finally:
        loop.close()

    assert result.status == "success"
    assert result.rounds == 3
    assert seen[0] == ""
    assert seen[1] != ""  # 第二次尝试拿到了失败原因
    assert submitted == "ok"
    # 前两次失败没有留下残余文件，value.txt 回到了基线
    assert (repo / "value.txt").read_text(encoding="utf-8").strip() == "base"


def test_untracked_leftovers_are_cleaned_on_rollback(tmp_path):
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", gate_is("ok"),
                      Budget(rounds=3, max_files=5, max_lines=50, minutes=5))
    try:
        def attempt(ctx):
            (loop.worktree / "junk.py").write_text("print(1)\n", encoding="utf-8")
            (loop.worktree / "value.txt").write_text("bad\n", encoding="utf-8")

        result = loop.run(attempt)
        leftovers = sorted(p.name for p in loop.worktree.iterdir() if not p.name.startswith("."))
    finally:
        loop.close()
    assert result.status == "stuck"
    assert leftovers == ["notes.txt", "value.txt"]


def test_dead_end_backtracks_to_earlier_green_point(tmp_path):
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", gate_is("ok"),
                      Budget(rounds=8, max_files=5, max_lines=50, minutes=5))
    rounds: list[int] = []
    try:
        def attempt(ctx):
            rounds.append(ctx.round_no)
            (loop.worktree / "value.txt").write_text("ok\n", encoding="utf-8")
            if ctx.round_no > 1:
                # 通过第一轮绿点后再动另一个文件：每次失败原因相同，构成死路
                (loop.worktree / "notes.txt").write_text("broken\n", encoding="utf-8")

        # 第 1 轮通过，但里程碑未完成 → 续期继续；之后同一绿点反复失败
        result = loop.run(attempt, milestone_done=lambda n: n >= 2)
        green_count = len(result.green_points)
    finally:
        loop.close()
    assert result.status == "stuck"
    assert green_count == 1  # 走不通的绿点被退掉，只剩基线
    assert result.rounds > 3


def test_single_round_change_over_limit_stops(tmp_path):
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", gate_is("ok"),
                      Budget(rounds=5, max_files=2, max_lines=5, minutes=5))
    try:
        def attempt(ctx):
            (loop.worktree / "value.txt").write_text("ok\n" + "x\n" * 40, encoding="utf-8")

        result = loop.run(attempt)
    finally:
        loop.close()
    assert result.status == "budget"
    assert "超限" in result.reason


def test_green_commit_excludes_cache_files(tmp_path):
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", gate_is("ok"),
                      Budget(rounds=3, max_files=5, max_lines=50, minutes=5))
    try:
        def attempt(ctx):
            (loop.worktree / "value.txt").write_text("ok\n", encoding="utf-8")
            cache = loop.worktree / "__pycache__"
            cache.mkdir(exist_ok=True)
            (cache / "x.cpython-312.pyc").write_bytes(b"\x00\x01")

        result = loop.run(attempt)
        committed = git(loop.worktree, "show", "--name-only", "--pretty=format:", "HEAD")
    finally:
        loop.close()
    assert result.status == "success"
    assert "value.txt" in committed
    assert ".pyc" not in committed


def test_no_progress_hint_reaches_next_attempt(tmp_path):
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", gate_is("ok"),
                      Budget(rounds=5, max_files=5, max_lines=50, minutes=5))
    hints: list[str] = []
    try:
        def attempt(ctx):
            hints.append(ctx.feedback)
            (loop.worktree / "value.txt").write_text("same-bad\n", encoding="utf-8")

        loop.run(attempt)
    finally:
        loop.close()
    assert any("必须换一个完全不同的思路" in hint for hint in hints)


def test_stale_worktree_is_reclaimed(tmp_path):
    repo = make_repo(tmp_path)
    worktree = tmp_path / "wt"
    first = CodingLoop(repo, worktree, gate_is("ok"),
                       Budget(rounds=2, max_files=5, max_lines=50, minutes=5))
    first.prepare()          # 模拟上次异常退出：副本已存在但没关闭
    second = CodingLoop(repo, worktree, gate_is("ok"),
                        Budget(rounds=2, max_files=5, max_lines=50, minutes=5))
    try:
        def attempt(ctx):
            (second.worktree / "value.txt").write_text("ok\n", encoding="utf-8")

        result = second.run(attempt)
    finally:
        second.close()
    assert result.status == "success"


def test_foreign_directory_is_rejected(tmp_path):
    repo = make_repo(tmp_path)
    foreign = tmp_path / "not-a-worktree"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("x", encoding="utf-8")
    loop = CodingLoop(repo, foreign, gate_is("ok"),
                      Budget(rounds=2, max_files=5, max_lines=50, minutes=5))
    with pytest.raises(RuntimeError, match="无法回收"):
        loop.prepare()


def test_policy_blocks_exit_patching(tmp_path):
    """实测过的攻击：把 sys.exit 替换掉，让永远失败的门禁返回 0。"""
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", [sys.executable, "-c", "import sys; sys.exit(0)"],
                      Budget(rounds=3, max_files=5, max_lines=50, minutes=5))
    try:
        def attempt(ctx):
            (loop.worktree / "calc.py").write_text(
                "import sys\nsys.exit = lambda code=0: None\n", encoding="utf-8")

        result = loop.run(attempt)
    finally:
        loop.close()
    assert result.status == "stuck"
    assert any("绕过校验" in item.output_tail for item in result.attempts)
    assert not any(item.passed for item in result.attempts)


def test_deleted_worktree_directory_is_pruned(tmp_path):
    """手动 rm -rf 副本目录后，git 仍有注册残留；下一次必须能自愈。"""
    import shutil

    repo = make_repo(tmp_path)
    worktree = tmp_path / "wt"
    first = CodingLoop(repo, worktree, gate_is("ok"),
                       Budget(rounds=2, max_files=5, max_lines=50, minutes=5))
    first.prepare()
    shutil.rmtree(worktree)          # 模拟外部删除，不调用 close()
    second = CodingLoop(repo, worktree, gate_is("ok"),
                        Budget(rounds=2, max_files=5, max_lines=50, minutes=5))
    try:
        def attempt(ctx):
            (second.worktree / "value.txt").write_text("ok\n", encoding="utf-8")

        result = second.run(attempt)
    finally:
        second.close()
    assert result.status == "success"


def test_pre_staged_junk_does_not_enter_green_commit(tmp_path):
    """外部执行器会自己 git add；排除规则必须能扛住已暂存的文件。"""
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", gate_is("ok"),
                      Budget(rounds=2, max_files=5, max_lines=50, minutes=5))
    try:
        def attempt(ctx):
            (loop.worktree / "value.txt").write_text("ok\n", encoding="utf-8")
            (loop.worktree / ".gitignore").write_text(".aider*\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=loop.worktree, check=True,
                           capture_output=True)

        result = loop.run(attempt)
        committed = git(loop.worktree, "show", "--name-only", "--pretty=format:", "HEAD")
    finally:
        loop.close()
    assert result.status == "success"
    assert "value.txt" in committed
    assert ".gitignore" not in committed


def test_clone_isolation_keeps_green_points(tmp_path):
    """opencode 在 worktree 里会卡住，克隆隔离要能完整跑通绿点与回退。"""
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "clone", gate_is("ok"),
                      Budget(rounds=3, max_files=5, max_lines=50, minutes=5),
                      isolation="clone")
    try:
        def attempt(ctx):
            (loop.worktree / "value.txt").write_text("bad\n", encoding="utf-8")
            if ctx.round_no > 1:
                (loop.worktree / "value.txt").write_text("ok\n", encoding="utf-8")

        result = loop.run(attempt)
        committed = git(loop.worktree, "show", "--name-only", "--pretty=format:", "HEAD")
    finally:
        loop.close()
    assert result.status == "success"
    assert result.rounds == 2
    assert "value.txt" in committed
    # 克隆关掉后目录应当消失，且不影响原仓库
    assert not (tmp_path / "clone").exists()
    assert (repo / "value.txt").read_text(encoding="utf-8").strip() == "base"


def test_new_file_cannot_bypass_single_round_budget(tmp_path):
    """新建文件必须计入单轮预算：否则新建一个大文件就能绕过改动上限。"""
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", gate_is("ok"),
                      Budget(rounds=3, max_files=2, max_lines=5, minutes=5))
    try:
        def attempt(ctx):
            (loop.worktree / "value.txt").write_text("ok\n", encoding="utf-8")
            (loop.worktree / "big.py").write_text("x = 1\n" * 20, encoding="utf-8")

        result = loop.run(attempt)
    finally:
        loop.close()
    assert result.status == "budget"
    assert "超限" in result.reason


def test_attempt_stats_include_new_files(tmp_path):
    """改动统计要把新文件算进去：漏算会让界面与预算都失真。"""
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", gate_is("ok"),
                      Budget(rounds=3, max_files=5, max_lines=50, minutes=5))
    try:
        def attempt(ctx):
            (loop.worktree / "value.txt").write_text("ok\n", encoding="utf-8")
            (loop.worktree / "new_module.py").write_text("VALUE = 1\n", encoding="utf-8")

        result = loop.run(attempt)
        committed = git(loop.worktree, "show", "--name-only", "--pretty=format:", "HEAD")
    finally:
        loop.close()
    assert result.status == "success"
    assert result.attempts[0].files == 2   # value.txt + new_module.py
    assert result.attempts[0].lines == 3    # 改 1 增 1 删 + 新增 1 行
    assert "new_module.py" in committed


def test_repeated_new_file_is_flagged_as_same_approach(tmp_path):
    """只新建文件的两轮改动，指纹也要能认出「还是那一个文件」，否则模型会无限重复。"""
    repo = make_repo(tmp_path)
    loop = CodingLoop(repo, tmp_path / "wt", gate_is("ok"),
                      Budget(rounds=5, max_files=5, max_lines=50, minutes=5))
    hints = []
    try:
        def attempt(ctx):
            hints.append(ctx.feedback)
            (loop.worktree / "same_new.py").write_text("VALUE = 1\n", encoding="utf-8")

        result = loop.run(attempt)
    finally:
        loop.close()
    assert result.status == "stuck"
    assert any("必须换一个完全不同的思路" in hint for hint in hints)


def test_git_calls_are_exempt_from_dubious_ownership():
    """git 的「可疑属主」保护会因部署身份不同而随机拒绝操作。

    服务与 worker 都以非 root 运行，代码根却可能属主不同（迁移目录、root 建库），
    clone 会直接报 dubious ownership。所有 git 调用都要带单次豁免。
    """
    from rag_tech_retriever.platform.coding_loop import GIT_SAFE

    assert GIT_SAFE == ("git", "-c", "safe.directory=*")
    source = Path(coding_loop.__file__).read_text(encoding="utf-8")
    # 每处 git 调用都要带豁免前缀，不能有裸的 ["git", ...]
    assert '["git",' not in source
    for name in ("aider_attempt", "opencode_attempt", "loop_service"):
        text = Path(coding_loop.__file__).with_name(f"{name}.py").read_text(encoding="utf-8")
        assert '["git",' not in text, f"{name}.py 还有没加豁免的 git 调用"


def test_safe_directory_config_lists_only_given_repos(tmp_path):
    """可信目录配置只能包含已登记的代码根，不能用通配符放开任意目录。"""
    from rag_tech_retriever.platform.coding_loop import write_safe_directory_config

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)

    config = write_safe_directory_config(tmp_path / "conf", [repo])
    text = config.read_text(encoding="utf-8")

    assert text.startswith("[safe]")
    assert "*" not in text
    assert repo.as_posix() in text
    assert (repo / ".git").as_posix() in text
    assert other.as_posix() not in text
    # git 配置里路径必须用正斜杠，反斜杠会被当成转义符
    assert "\\" not in text


def test_git_env_points_global_config_at_file(tmp_path):
    """git 子进程靠 GIT_CONFIG_GLOBAL 拿到可信目录：-c 传不进 clone 的子进程。"""
    from rag_tech_retriever.platform.coding_loop import git_env

    config = tmp_path / "conf"
    env = git_env(config)
    assert env["GIT_CONFIG_GLOBAL"] == str(config)
    # 没给配置时不能动用户的全局 git 配置
    assert "GIT_CONFIG_GLOBAL" not in git_env(None)
