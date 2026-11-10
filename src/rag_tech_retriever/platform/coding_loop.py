"""全自动编码循环：隔离副本 + 绿点检查点 + 失败换方向。

设计要点（对应评审意见）：
- 预算按任务档位给，且校验通过后可以续期，避免"一开始定少了"半途而废。
- 每通过一次校验就打一个绿点（git commit）。失败一律回退到最近绿点，
  再把"试过什么、错在哪"带回给下一次尝试，要求换方向，而不是从头再来。
- 同一绿点连续失败到上限，就回退到上一个绿点，扩大搜索范围。
- 所有写操作发生在 worktree 副本里，主工作目录不受影响；副本用完即删。

本模块只负责调度与 git 状态机，不直接调用模型：外部传入 attempt 回调，
测试里可以换成确定性假实现，生产里接 Agent。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# 档位：轮次 / 最大文件数 / 最大改动行 / 时限（分钟）
TIERS = {
    "patch": (6, 3, 80, 10),
    "feature": (20, 10, 600, 40),
    "epic": (60, 30, 3000, 180),
}

SHORTSTAT = re.compile(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?")

# 校验命令会生成缓存文件；它们不能进绿点提交，否则回退点里混着构建产物。
EXCLUDES = ("**/__pycache__/**", "**/*.pyc", "**/.pytest_cache/**", "**/.ruff_cache/**",
            "**/.mypy_cache/**", "**/node_modules/**", "**/.venv/**", "**/.DS_Store",
            "**/.aider*", ".gitignore", "**/.gitignore")

# 这些写法能把「校验进程」本身劫持掉，让失败变成通过。
# 实测：模型为了满足一个不可能通过的门禁，直接替换了 sys.exit。
SUSPICIOUS = (
    (r"\.exit\s*=", "替换 exit 实现"),
    (r"\bsys\._getframe\b", "读取调用栈来判断调用方"),
    (r"\b__builtins__\b", "改写内建命名空间"),
    (r"\bsys\.modules\s*\[", "篡改已加载模块"),
    (r"\batexit\.register\b", "注册退出钩子"),
    (r"\b(os|sys)\._exit\b", "绕过正常退出流程"),
    (r"\bsitecustomize\b|\busercustomize\b", "注入启动钩子"),
    (r"\bmonkeypatch\b", "猴补丁"),
)
FORBIDDEN_NAMES = {"sitecustomize.py", "usercustomize.py", "conftest.py"}


@dataclass
class Budget:
    """一次运行的预算；续期只加轮次和时间，不放宽单轮改动上限。"""

    rounds: int
    max_files: int
    max_lines: int
    minutes: int
    renewals: int = 0
    max_renewals: int = 3

    @classmethod
    def tier(cls, name: str) -> Budget:
        if name not in TIERS:
            raise ValueError(f"未知预算档位：{name}")
        rounds, files, lines, minutes = TIERS[name]
        return cls(rounds, files, lines, minutes)

    def renew(self) -> bool:
        """校验通过一个里程碑后续期 50%；用尽次数返回 False。"""
        if self.renewals >= self.max_renewals:
            return False
        self.renewals += 1
        self.rounds += max(1, self.rounds // 2)
        self.minutes += max(1, self.minutes // 2)
        return True


@dataclass
class Attempt:
    """一次尝试的留痕：改了多少、为什么没过。"""

    round_no: int
    files: int
    lines: int
    passed: bool
    signature: str
    output_tail: str


@dataclass
class GreenPoint:
    """一个通过校验的稳定点，回退目标。"""

    commit: str
    round_no: int
    note: str


@dataclass
class AttemptContext:
    """交给模型（或假实现）的现场信息。"""

    round_no: int
    green: GreenPoint
    feedback: str
    tried: list[str] = field(default_factory=list)
    remaining_rounds: int = 0


@dataclass
class LoopResult:
    status: str  # success / budget / stuck / timeout / error
    rounds: int
    green_points: list[GreenPoint]
    attempts: list[Attempt]
    reason: str = ""
    last_output: str = ""


def _rmtree(path: Path) -> None:
    """删目录：git 对象是只读的，Windows 上直接删会失败，先改权限再删。"""
    def retry(func, target, _exc):
        try:
            os.chmod(target, 0o700)
            func(target)
        except OSError:
            pass

    try:
        # ignore_errors 与 onerror 互斥：同传时 onerror 根本不会被调用。
        shutil.rmtree(path, onerror=retry if os.name == "nt" else None)
    except OSError:
        pass


class CodingLoop:
    """在一个独立 worktree 里反复「改 → 校验 → 绿点或回退」。"""

    def __init__(self, repo: Path, worktree: Path, gate: Sequence[str], budget: Budget,
                 *, branch: str = "agent/auto", isolation: str = "worktree",
                 clock: Callable[[], float] = time.monotonic,
                 gate_timeout: int = 300, dead_end_limit: int = 3,
                 no_progress_limit: int = 2) -> None:
        self.repo = Path(repo).resolve()
        self.worktree = Path(worktree).resolve()
        self.gate = list(gate)
        self.budget = budget
        self.branch = branch
        # worktree：共享对象库、开销最小；clone：独立 .git。
        # opencode 在 worktree 里会卡在会话 busy（实测），必须用 clone。
        self.isolation = isolation
        self.clock = clock
        self.gate_timeout = gate_timeout
        self.dead_end_limit = dead_end_limit
        self.no_progress_limit = no_progress_limit
        self._started = 0.0
        self._prepared = False

    # ---------- git 基础操作 ----------

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(["git", *args], cwd=self.worktree, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=False)
        if check and result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} 失败：{result.stderr.strip()[:300]}")
        return result

    def prepare(self) -> GreenPoint:
        """建副本分支并记录基线绿点；重复调用不会重建。"""
        if self._prepared:
            return self.green_points[0]
        if self.isolation == "clone":
            return self._prepare_clone()
        # 目录被手动删掉时，git 里仍有注册残留，不清掉会导致 worktree add 直接失败。
        subprocess.run(["git", "worktree", "prune"], cwd=self.repo,
                       capture_output=True, text=True, check=False)
        if self.worktree.exists() and any(self.worktree.iterdir()):
            # 上次异常退出会留下副本：先尝试按 git worktree 回收，回收失败才报错。
            removed = subprocess.run(["git", "worktree", "remove", "--force", str(self.worktree)],
                                     cwd=self.repo, capture_output=True, text=True, check=False)
            if removed.returncode != 0 or (self.worktree.exists()
                                           and any(self.worktree.iterdir())):
                raise RuntimeError(
                    f"副本目录已存在且无法回收：{self.worktree}；请先删除它，或用 --worktree 换一个位置")
        self.worktree.parent.mkdir(parents=True, exist_ok=True)
        added = subprocess.run(
            ["git", "worktree", "add", "-B", self.branch, str(self.worktree), "HEAD"],
            cwd=self.repo, capture_output=True, text=True, check=False)
        if added.returncode != 0:
            raise RuntimeError(f"无法创建副本：{added.stderr.strip()[:300]}")
        self._prepared = True
        self._started = self.clock()
        head = self._git("rev-parse", "HEAD").stdout.strip()
        self.green_points = [GreenPoint(head, 0, "基线")]
        return self.green_points[0]

    def _prepare_clone(self) -> GreenPoint:
        if self.worktree.exists():
            _rmtree(self.worktree)
        self.worktree.parent.mkdir(parents=True, exist_ok=True)
        added = subprocess.run(["git", "clone", "--quiet", "--local", "--shared",
                                str(self.repo), str(self.worktree)],
                               capture_output=True, text=True, check=False)
        if added.returncode != 0:
            raise RuntimeError(f"无法创建克隆副本：{added.stderr.strip()[:300]}")
        self._prepared = True
        self._started = self.clock()
        self._git("checkout", "-q", "-B", self.branch)
        head = self._git("rev-parse", "HEAD").stdout.strip()
        self.green_points = [GreenPoint(head, 0, "基线")]
        return self.green_points[0]

    def close(self) -> None:
        """删除副本；绿点提交留在分支上，不推远端。"""
        if not self._prepared:
            return
        if self.isolation == "clone":
            _rmtree(self.worktree)
            self._prepared = False
            return
        subprocess.run(["git", "worktree", "remove", "--force", str(self.worktree)],
                       cwd=self.repo, capture_output=True, text=True, check=False)
        subprocess.run(["git", "worktree", "prune"], cwd=self.repo, capture_output=True,
                       text=True, check=False)
        self._prepared = False

    def _untracked_names(self) -> list[str]:
        """未跟踪的新文件；排除规则与绿点提交保持一致，缓存目录不算改动。"""
        out = self._git("ls-files", "--others", "--exclude-standard", "--", ".",
                        *[f":(exclude){pattern}" for pattern in EXCLUDES],
                        check=False).stdout
        return [name.strip() for name in out.split("\n") if name.strip()]

    def _untracked_stats(self) -> tuple[int, int]:
        """新文件按整文件计入行数，与 git 对新增文件的统计口径一致。

        不能靠 `git add -N` 把新文件塞进 diff：那会让 `git clean -fd` 认得它，
        回退时就不再删除本轮新增的文件了。
        """
        names = self._untracked_names()
        lines = 0
        for name in names:
            path = self.worktree / name
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:8192]:
                continue  # 二进制文件不计行数，与 git --shortstat 一致
            lines += data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        return len(names), lines

    # ---------- 状态 ----------

    def _changed(self, since: str) -> tuple[int, int]:
        """统计本轮改动：已跟踪文件的差异 + 未跟踪的新文件。

        新文件必须计入：否则新建一个大文件就能绕过单轮改动预算。
        """
        text = self._git("diff", "--shortstat", since, check=False).stdout.strip()
        match = SHORTSTAT.search(text)
        files = int(match.group(1)) if match else 0
        lines = (int(match.group(2) or 0) + int(match.group(3) or 0)) if match else 0
        new_files, new_lines = self._untracked_stats()
        return files + new_files, lines + new_lines

    def _diff_signature(self) -> str:
        """本轮改动指纹：用来判断模型是不是在重复做同一件事。

        以 HEAD（当前绿点）为基准并带上新文件名单：只看 `git diff` 会漏掉
        已暂存的改动，也看不到新建的文件，两轮就会算出同一个空指纹。
        """
        tracked = self._git("diff", "HEAD", "--stat", check=False).stdout.strip()
        names = self._untracked_names()
        parts = []
        if tracked:
            parts.append(tracked[-300:])
        if names:
            parts.append("新增：" + "、".join(names[:20]))
        return "\n".join(parts)[:500]

    def _run_gate(self) -> tuple[bool, str]:
        try:
            result = subprocess.run(self.gate, cwd=self.worktree, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace",
                                    timeout=self.gate_timeout, check=False)
        except subprocess.TimeoutExpired:
            return False, f"校验超时（>{self.gate_timeout}s）"
        tail = (result.stdout + result.stderr).strip()[-1200:]
        return result.returncode == 0, tail

    def _commit_green(self, round_no: int, note: str) -> GreenPoint:
        # 没有实际改动时不产生新提交：git 拒绝空提交，而且重复绿点会让回退语义变形。
        # aider 等外部执行器会自己 git add，排除规则管不到暂存区里的旧内容，
        # 所以先清空暂存区，再按排除规则重新暂存。
        self._git("reset", "-q")
        self._git("add", "-A", "--", ".",
                  *[f":(exclude){pattern}" for pattern in EXCLUDES])
        # 只有缓存文件变化时，暂存区是空的：此时不产生新绿点，避免 git 拒绝空提交。
        if not self._git("diff", "--cached", "--name-only").stdout.strip():
            return self.green_points[-1]
        self._git("-c", "user.name=auto-loop", "-c", "user.email=auto-loop@local",
                  "commit", "-m", f"green: round {round_no} {note}".strip())
        head = self._git("rev-parse", "HEAD").stdout.strip()
        point = GreenPoint(head, round_no, note)
        self.green_points.append(point)
        return point

    def _violations(self, since: str) -> list[str]:
        """扫描本轮改动里有没有「劫持校验进程」的写法。

        这不是代码风格检查：这些写法能让一个不可能通过的门禁返回 0，
        于是绿点变成假绿点，后面所有回退都退到错误状态上。
        """
        names = self._git("diff", "--name-only", since, check=False).stdout.split("\n")
        names += self._git("ls-files", "--others", "--exclude-standard",
                           check=False).stdout.split("\n")
        found: list[str] = []
        for name in {item.strip() for item in names if item.strip()}:
            path = self.worktree / name
            if path.name in FORBIDDEN_NAMES or path.suffix == ".pth":
                found.append(f"{name}：注入型文件")
                continue
            if not path.is_file() or path.suffix not in {".py", ".pyi"}:
                continue
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pattern, label in SUSPICIOUS:
                if re.search(pattern, body):
                    found.append(f"{name}：{label}")
        return found

    def _rollback(self, point: GreenPoint) -> None:
        self._git("reset", "--hard", point.commit)
        self._git("clean", "-fd")

    # ---------- 主循环 ----------

    def run(self, attempt: Callable[[AttemptContext], None], *,
            milestone_done: Callable[[int], bool] | None = None) -> LoopResult:
        """驱动循环，直到通过、预算耗尽或连续死路。"""
        self.prepare()
        rounds_used = 0
        attempts: list[Attempt] = []
        feedback = ""
        stuck_at_green = 0
        last_signature = ""

        while rounds_used < self.budget.rounds:
            if (self.clock() - self._started) / 60 > self.budget.minutes:
                return LoopResult("timeout", rounds_used, self.green_points, attempts,
                                  "超出时限", feedback)
            green = self.green_points[-1]
            rounds_used += 1
            context = AttemptContext(
                round_no=rounds_used, green=green, feedback=feedback,
                tried=[a.signature for a in attempts],  # 供模型参考「试过什么」
                remaining_rounds=self.budget.rounds - rounds_used,
            )

            try:
                attempt(context)
            except Exception as exc:  # noqa: BLE001 - 失败要变成一轮反馈，不能让循环整体崩掉
                self._rollback(green)
                message = f"本轮执行异常：{exc}"[:800]
                attempts.append(Attempt(rounds_used, 0, 0, False, "error", message))
                feedback = message
                stuck_at_green = stuck_at_green + 1 if last_signature == "error" else 0
                last_signature = "error"
                continue

            files, lines = self._changed(green.commit)
            violations = self._violations(green.commit)
            if violations:
                self._rollback(green)
                message = "检测到绕过校验的写法，本轮作废：" + "；".join(violations[:4])
                attempts.append(Attempt(rounds_used, files, lines, False, "policy", message))
                feedback = message + "\n请改实现本身，不要替换 sys.exit / 内建 / 启动钩子。"
                stuck_at_green = stuck_at_green + 1 if last_signature == "policy" else 1
                last_signature = "policy"
                continue
            if files > self.budget.max_files or lines > self.budget.max_lines:
                self._rollback(green)
                attempts.append(Attempt(rounds_used, files, lines, False, "budget",
                                        f"改动超限：{files} 文件 / {lines} 行"))
                return LoopResult("budget", rounds_used, self.green_points, attempts,
                                  f"单轮改动超限（{files} 文件 / {lines} 行）")

            passed, output = self._run_gate()
            signature = self._diff_signature()
            attempts.append(Attempt(rounds_used, files, lines, passed,
                                    signature if not passed else "green", output))
            if passed:
                note = f"（{files} 文件 / {lines} 行）"
                self._commit_green(rounds_used, note)
                stuck_at_green = 0
                last_signature = ""
                feedback = ""
                done = milestone_done(rounds_used) if milestone_done else True
                if not done:
                    self.budget.renew()  # 里程碑达成，续期继续
                    continue
                return LoopResult("success", rounds_used, self.green_points, attempts, "校验通过")
            feedback = output[-800:]
            self._rollback(green)
            if signature and signature == last_signature:
                stuck_at_green += 1
            else:
                stuck_at_green = 0
            last_signature = signature
            if stuck_at_green >= self.no_progress_limit:
                feedback = "改动与前几次完全相同，必须换一个完全不同的思路。\n" + feedback
            if stuck_at_green >= self.dead_end_limit and len(self.green_points) > 1:
                # 这个绿点已走不通：退回上一个，扩大搜索范围
                self.green_points.pop()
                self._rollback(self.green_points[-1])
                stuck_at_green = 0
                last_signature = ""
                feedback = "回退到更早的稳定点，请重新选择方向。\n" + feedback

        return LoopResult("stuck", rounds_used, self.green_points, attempts,
                          "轮次用尽仍未通过", feedback)
