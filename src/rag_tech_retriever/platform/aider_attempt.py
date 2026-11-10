"""把 Aider 接成「一次尝试」的执行器。

分工：
- Aider 负责改：它有仓库地图（repo map）、多文件一致性、SEARCH/REPLACE 编辑格式。
- 我们负责判：门禁、绿点、回退、预算、绕过校验的写法扫描。

三条硬约束，缺一条就会出问题：
1. ``--no-auto-commits``：否则 Aider 自己提交，绿点语义被打乱，回退退不干净。
2. 文件清单显式传入，不让它顺手改没授权的目录。
3. 模型走我们配置的 OpenAI 兼容端点，密钥只在进程环境里，不写进仓库。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
             ".pytest_cache", ".mypy_cache", ".ruff_cache"}
TEXT_SUFFIX = {".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".go", ".rs", ".java", ".rb",
               ".json", ".yaml", ".yml", ".md", ".txt", ".toml", ".ini", ".cfg", ".css",
               ".html", ".sql", ".sh"}
MAX_FILES = 20


class AiderAttempt:
    """一轮 = 调一次 aider；改动是否合格由 CodingLoop 的门禁判定。"""

    def __init__(self, config: dict, root: Path, task: str, *, files: Sequence[str] = (),
                 readonly: Sequence[str] = (), binary: str = "aider", timeout: int = 240,
                 map_tokens: int = 1024,
                 runner: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
        self.config = dict(config)
        self.root = Path(root).resolve()
        self.task = task
        self.files = list(files)
        self.readonly = tuple(item.strip("/\\") for item in readonly if item.strip())
        self.binary = binary
        self.timeout = timeout
        self.map_tokens = map_tokens
        self.runner = runner or subprocess.run
        self.history_dir = Path(tempfile.gettempdir()) / "shilie-aider"
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def _blocked(self, rel: str) -> bool:
        return any(rel == item or rel.startswith(item + "/") for item in self.readonly)

    def _default_files(self) -> list[str]:
        found: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(self.root).parts):
                continue
            if path.suffix.lower() not in TEXT_SUFFIX:
                continue
            rel = path.relative_to(self.root).as_posix()
            if self._blocked(rel):
                continue
            found.append(rel)
            if len(found) >= MAX_FILES:
                break
        return found

    def command(self, feedback: str) -> list[str]:
        message = self.task
        if feedback:
            message += "\n\n上一轮校验没有通过，错误输出如下，请针对性修掉：\n" + feedback[-1500:]
        files = self.files or self._default_files()
        return [
            self.binary, "--model", f"openai/{self.config['model']}",
            "--yes", "--no-auto-commits", "--no-stream", "--analytics-disable",
            # 不让它改 .gitignore；历史文件写到系统临时目录，
            # 写进 .git/ 会让 aider 自己在 append_chat_history 里崩掉（实测）。
            "--no-add-gitignore-files",
            "--chat-history-file", str(self.history_dir / "chat.md"),
            "--input-history-file", str(self.history_dir / "input.txt"),
            "--llm-history-file", str(self.history_dir / "llm.jsonl"),
            "--map-tokens", str(self.map_tokens), "--message", message, *files,
        ]

    def environment(self) -> dict:
        env = dict(os.environ)
        env["OPENAI_API_BASE"] = str(self.config.get("base_url", ""))
        env["OPENAI_API_KEY"] = str(self.config.get("api_key", ""))
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def _changed_paths(self) -> list[str]:
        result = self.runner(["git", "status", "--porcelain"], cwd=self.root, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=30,
                             check=False)
        names: list[str] = []
        for line in (result.stdout or "").splitlines():
            name = line[3:].strip()
            if " -> " in name:
                name = name.split(" -> ")[-1]
            if name:
                names.append(name)
        return names

    def attempt(self, context) -> None:
        result = self.runner(
            self.command(context.feedback), cwd=self.root, env=self.environment(),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            # 非交互环境下没有 stdin，不关掉会一直等输入（实测卡死 400 秒）。
            stdin=subprocess.DEVNULL, timeout=self.timeout, check=False)
        tail = ((result.stdout or "") + (result.stderr or ""))[-600:].strip()
        if result.returncode != 0:
            raise RuntimeError(f"aider 执行失败（{result.returncode}）：{tail[:300]}")
        touched = self._changed_paths()
        blocked = [name for name in touched if self._blocked(name)]
        if blocked:
            # 改测试就能"通过"，这类绿点必须作废。
            raise RuntimeError("修改了只读路径：" + "、".join(blocked[:4]))
        context.tried.append(tail.replace("\n", " ")[:160] or f"round {context.round_no}")
