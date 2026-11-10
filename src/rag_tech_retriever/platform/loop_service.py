"""把「自动编码循环」做成可被接口调用的一层。

职责：解析仓库 → 选执行器（opencode/aider/model）→ 跑循环 → 落一条运行记录。
不做 HTTP 解析，也不碰前端；路由只负责校验与转交。
"""

from __future__ import annotations

import os
import shlex
import time
from pathlib import Path

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.aider_attempt import AiderAttempt
from rag_tech_retriever.platform.coding_loop import Budget, CodingLoop
from rag_tech_retriever.platform.model_attempt import EditingModel
from rag_tech_retriever.platform.opencode_attempt import OpenCodeAttempt

ENGINES = ("opencode", "aider", "model")
TIERS = ("patch", "feature", "epic")


class LoopService:
    """一次自动编码运行：隔离副本 + 绿点 + 回退 + 落记录。"""

    def __init__(self, store, connection, *, opencode_bin: str = "/opt/shilie/opencode/opencode",
                 opencode_home: str = "/opt/shilie/opencode-home",
                 supervisor_script: str = "", aider_bin: str = "aider") -> None:
        self.store = store
        self.connection = connection
        self.opencode_bin = opencode_bin
        self.opencode_home = opencode_home
        self.supervisor_script = supervisor_script
        self.aider_bin = aider_bin

    def _worker(self, engine: str, config: dict, worktree: Path, task: str,
                log_path: str = ""):
        readonly = ["tests", "test", "conftest.py", "pyproject.toml", "requirements.txt"]
        if engine == "opencode":
            # systemd-run 需要 root（polkit）；服务以普通用户跑时会卡在授权上。
            supervisor = "systemd" if os.geteuid() == 0 and self.supervisor_script else ""
            return OpenCodeAttempt(config, worktree, task, binary=self.opencode_bin,
                                   port=0, home=self.opencode_home, readonly=readonly,
                                   timeout=300, supervisor=supervisor,
                                   supervisor_script=self.supervisor_script,
                                   log_path=log_path)
        if engine == "aider":
            return AiderAttempt(config, worktree, task, binary=self.aider_bin,
                                readonly=readonly)
        return EditingModel(config, worktree, task, readonly=readonly)

    def run(self, repo: Path, task: str, gate: str, engine: str, tier: str,
            writable: bool = True) -> dict:
        if engine not in ENGINES:
            raise DomainError("不支持的执行器")
        if tier not in TIERS:
            raise DomainError("不支持的预算档位")
        if not writable:
            raise DomainError("该代码根目录未开启写入")
        repo = Path(repo).resolve()
        if not (repo / ".git").exists():
            raise DomainError("目标目录不是 git 仓库，无法做绿点与回退")
        config = self.connection.load()
        if not all(config.get(key) for key in ("api_key", "base_url", "model")):
            raise DomainError("尚未配置模型连接")

        worktree = repo.parent / f".auto-loop-{repo.name}"
        isolation = "clone" if engine == "opencode" else "worktree"
        loop = CodingLoop(repo, worktree, shlex.split(gate), Budget.tier(tier),
                          isolation=isolation)
        # 日志要落在可见可写目录：服务开了 PrivateTmp，/tmp 里的日志外面看不到。
        log_dir = Path(self.opencode_home).parent if self.opencode_home else worktree.parent
        worker = self._worker(engine, config, worktree, task,
                              log_path=str(log_dir / "opencode-child.log"))
        started = time.time()
        diff = ""
        try:
            result = loop.run(worker.attempt)
            # 必须在副本被删掉之前取 diff。
            diff = self._diff(result, worktree)
        finally:
            closer = getattr(worker, "close", None)
            if callable(closer):
                closer()
            if (worktree / ".git").exists():
                loop.close()
        summary = {
            "status": result.status,
            "rounds": result.rounds,
            "reason": result.reason,
            "green_points": len(result.green_points),
            "engine": engine,
            "tier": tier,
            "repo": str(repo),
            "task": task,
            "gate": gate,
            "duration_ms": int((time.time() - started) * 1000),
            "attempts": [{"round": item.round_no, "files": item.files, "lines": item.lines,
                          "passed": item.passed, "why": (item.output_tail or "")[-300:]}
                         for item in result.attempts],
            "diff": diff,
        }
        row = self.store.save("workflow_run", {
            "kind": "loop",
            "title": f"自动编码：{task[:40]}",
            "status": "completed" if result.status == "success" else "failed",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "input": {"task": task, "gate": gate, "repo": str(repo)},
            "summary": summary,
        })
        return {"id": row["id"], "version": row["version"], **summary}

    @staticmethod
    def _diff(result, worktree: Path) -> str:
        """把绿点相对基线的改动取出来，供界面展示。"""
        if len(result.green_points) < 2 or not worktree.exists():
            return ""
        import subprocess

        base = result.green_points[0].commit
        done = subprocess.run(["git", "diff", "--stat", base, result.green_points[-1].commit],
                              cwd=str(worktree), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False)
        return (done.stdout or "").strip()[:2000]
