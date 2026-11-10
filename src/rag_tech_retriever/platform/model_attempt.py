"""让模型执行一次「改代码」：读现状 + 上次失败原因 → 返回整文件写入。

为什么是整文件内容而不是 diff：解析成本低、失败可归因（写坏了就是写坏了），
在「自动循环 + 绿点回退」下不需要省那点 token——回退会兜住写坏的结果。

安全边界由调用方给：root 就是 worktree；readonly 里的路径一律拒绝写入
（测试、门禁脚本、依赖锁），避免「改测试让自己通过」这种退化。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rag_tech_retriever.common.provider import post_chat

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
             ".pytest_cache", ".mypy_cache", ".ruff_cache"}
TEXT_SUFFIX = {".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".go", ".rs", ".java", ".rb",
               ".json", ".yaml", ".yml", ".md", ".txt", ".toml", ".ini", ".cfg", ".css",
               ".html", ".sql", ".sh"}
SECRET_NAME = re.compile(r"(^\.env|\.pem$|^id_rsa|\.key$|credential|secret)", re.IGNORECASE)
FENCE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


@dataclass
class Edit:
    path: str
    content: str


class EditingModel:
    """一次尝试 = 一次模型调用 + 一批整文件写入。"""

    def __init__(self, config: dict, root: Path, task: str, *, readonly: Sequence[str] = (),
                 max_chars: int = 24000, max_files: int = 6, timeout: int = 120,
                 post: Callable[..., dict] | None = None) -> None:
        self.config = dict(config)
        self.root = Path(root).resolve()
        self.task = task
        self.readonly = tuple(item.strip("/\\") for item in readonly if item.strip())
        self.max_chars = max_chars
        self.max_files = max_files
        self.timeout = timeout
        self.post = post or post_chat
        self.last_raw = ""

    # ---------- 上下文 ----------

    def _text_files(self) -> list[Path]:
        found: list[Path] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(self.root).parts):
                continue
            if SECRET_NAME.search(path.name) or path.suffix.lower() not in TEXT_SUFFIX:
                continue
            found.append(path)
        return sorted(found)

    def _context(self) -> str:
        budget = self.max_chars
        blocks: list[str] = []
        for path in self._text_files():
            rel = path.relative_to(self.root).as_posix()
            try:
                body = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if len(body) > budget:
                body = body[:budget] + "\n…（截断）"
            blocks.append(f"--- {rel} ---\n{body}")
            budget -= len(body)
            if budget <= 0:
                break
        return "\n\n".join(blocks)

    def _prompt(self, task: str, feedback: str, tried: list[str]) -> list[dict]:
        readonly = "、".join(self.readonly) if self.readonly else "（无）"
        system = (
            "你是代码实现者。根据任务与现有代码，给出完整的新文件内容。\n"
            "只输出一个 JSON 对象，不要解释，不要代码围栏之外的内容：\n"
            '{"edits":[{"path":"相对路径","content":"完整文件内容"}],"note":"一句话说明改了什么"}\n'
            f"禁止修改这些路径（测试/门禁/依赖）：{readonly}。\n"
            "禁止修改测试来让校验通过；只能改实现。新建文件也用同样的 path 字段。"
        )
        user = f"任务：{task}\n\n当前文件：\n{self._context()}\n"
        if feedback:
            user += f"\n上次尝试失败，校验输出如下：\n{feedback[-1500:]}\n请修掉这个问题。\n"
        if tried:
            user += "\n已经试过但都失败的方向（不要重复）：\n" + "\n".join(
                f"- {item[:200]}" for item in tried[-3:]) + "\n"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # ---------- 解析与应用 ----------

    @staticmethod
    def parse(text: str) -> tuple[list[Edit], str]:
        """容忍代码围栏与前后缀说明，取第一个可解析的 JSON 对象。"""
        candidates = [text.strip()]
        candidates += [match.group(1).strip() for match in FENCE.finditer(text)]
        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict) and isinstance(payload.get("edits"), list):
                edits = [Edit(str(item["path"]), str(item["content"]))
                         for item in payload["edits"]
                         if isinstance(item, dict) and item.get("path") and "content" in item]
                return edits, str(payload.get("note") or "")
        return [], ""

    def _resolve(self, rel: str) -> Path:
        if Path(rel).is_absolute():
            raise ValueError(f"拒绝绝对路径：{rel}")
        target = (self.root / rel).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"越界路径：{rel}")
        if SECRET_NAME.search(target.name):
            raise ValueError(f"拒绝写入疑似密钥文件：{rel}")
        normalized = target.relative_to(self.root).as_posix()
        for blocked in self.readonly:
            if normalized == blocked or normalized.startswith(blocked + "/"):
                raise ValueError(f"该路径只读，禁止修改：{rel}")
        return target

    def apply(self, edits: Sequence[Edit]) -> list[str]:
        if len(edits) > self.max_files:
            names = "、".join(edit.path for edit in edits[self.max_files:])
            # 静默截断会让门禁报一个与真因无关的错；宁可整轮作废。
            raise ValueError(f"一次返回 {len(edits)} 个文件，超过上限 {self.max_files}：{names}")
        applied: list[str] = []
        for edit in edits:
            target = self._resolve(edit.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit.content, encoding="utf-8")
            applied.append(target.relative_to(self.root).as_posix())
        return applied

    # ---------- 交给循环 ----------

    def attempt(self, context) -> None:
        """CodingLoop 的回调：改完就返回，验收与回退由循环负责。"""
        messages = self._prompt(self.task, context.feedback, context.tried)
        body = {"model": self.config["model"], "messages": messages,
                "max_tokens": 4000, "temperature": 0.2}
        envelope = self.post(self.config, body, self.timeout, self.max_chars * 4)
        try:
            self.last_raw = envelope["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("模型未返回可解析内容") from exc
        edits, note = self.parse(self.last_raw)
        if not edits:
            raise RuntimeError("模型输出里没有可应用的 edits")
        self.apply(edits)
        context.tried.append(note or f"round {context.round_no}: {len(edits)} 个文件")
