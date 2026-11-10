"""受限代码工作区：路径禁锢、原子写入、逐次备份与差异回传。

安全边界
- 代码根目录只能由服务器管理员在 `config/agent-tools.yaml` 登记，模型不能自选路径。
- 所有相对路径在解析后必须仍位于登记的根目录内；符号链接指向外部同样被拒绝。
- 读操作跳过密钥文件与私密数据目录；写操作额外拒绝 `.git/`。
- 每次写入先备份、再原子替换、最后回传 unified diff；失败不留下半写文件。
- 命令执行默认关闭，只接受管理员白名单里的命令前缀，且不经 shell 解释。
"""
from __future__ import annotations

import difflib
import hashlib
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from rag_tech_retriever.domains.life_planning import DomainError

IDENT = re.compile(r"[a-z][a-z0-9_-]{0,40}\Z")
SECRET_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE)", re.IGNORECASE)
SECRET_NAME = re.compile(r"(^\.env|\.env$|\.pem$|\.key$|\.p12$|\.pfx$|^id_rsa|^id_ed25519)", re.IGNORECASE)

DEFAULTS = {
    "enabled": False,
    "roots": {},
    "max_read_bytes": 200_000,
    "max_write_bytes": 200_000,
    "max_scan_bytes": 400_000,
    "max_entries": 2000,
    "max_results": 200,
    "max_output_chars": 12_000,
    "max_patch_bytes": 200_000,
    "ignore_dirs": [".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
                    ".pytest_cache", ".ruff_cache", ".mypy_cache", ".code-backups"],
    "shell": {"enabled": False, "allow": [], "timeout_seconds": 60},
}

TOOL_NAMES = {"code_tree", "code_read", "code_search", "code_patch", "code_write", "code_shell"}
WRITE_TOOLS = {"code_patch", "code_write"}


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CodeWorkspace:
    """One registered root per agent; every path is resolved before use."""

    def __init__(self, project_root: Path, config: dict | None = None) -> None:
        value = config if config is not None else {}
        if not isinstance(value, dict) or set(value) - set(DEFAULTS):
            raise DomainError("代码工作区配置字段无效")
        merged = {**DEFAULTS, **value}
        shell = merged.get("shell") or {}
        if not isinstance(shell, dict) or set(shell) - {"enabled", "allow", "timeout_seconds"}:
            raise DomainError("代码命令配置字段无效")
        self.config = merged
        self.shell = {**DEFAULTS["shell"], **shell}
        if type(merged["enabled"]) is not bool or type(self.shell["enabled"]) is not bool:
            raise DomainError("代码工作区开关必须为布尔值")
        if (not isinstance(self.shell["allow"], list) or len(self.shell["allow"]) > 50
                or any(not isinstance(item, str) or not 1 <= len(item) <= 120
                       for item in self.shell["allow"])):
            raise DomainError("命令白名单必须为最多50个命令前缀")
        for key in ("max_read_bytes", "max_write_bytes", "max_scan_bytes", "max_entries",
                    "max_results", "max_output_chars", "max_patch_bytes"):
            if type(merged[key]) is not int or not 1 <= merged[key] <= 10_000_000:
                raise DomainError(f"代码工作区限制 {key} 必须为正整数")
        if type(self.shell["timeout_seconds"]) is not int or not 1 <= self.shell["timeout_seconds"] <= 600:
            raise DomainError("命令超时必须为 1–600 秒")
        ignore = merged.get("ignore_dirs", [])
        if not isinstance(ignore, list) or any(not isinstance(item, str) or not item for item in ignore):
            raise DomainError("忽略目录配置无效")
        self.ignore = set(ignore)
        self.project_root = project_root.resolve()
        self._roots = self._load_roots(merged.get("roots") or {})

    def _load_roots(self, raw: object) -> dict:
        if not isinstance(raw, dict) or len(raw) > 20:
            raise DomainError("代码根目录必须为最多20个登记项")
        roots: dict[str, dict] = {}
        for name, item in raw.items():
            if not isinstance(name, str) or not IDENT.fullmatch(name):
                raise DomainError("代码根目录标识只允许小写字母、数字、_ 或 -")
            if not isinstance(item, dict) or set(item) - {"path", "writable", "title"}:
                raise DomainError(f"代码根目录 {name} 配置字段无效")
            path = item.get("path")
            if not isinstance(path, str) or not path or len(path) > 400:
                raise DomainError(f"代码根目录 {name} 路径无效")
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = self.project_root / candidate
            resolved = candidate.resolve()
            if not resolved.is_dir():
                raise DomainError(f"代码根目录 {name} 不存在或不是目录")
            if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
                raise DomainError(f"代码根目录 {name} 不能指向文件系统根或用户主目录")
            writable = item.get("writable", False)
            if type(writable) is not bool:
                raise DomainError(f"代码根目录 {name} 写开关必须为布尔值")
            title = item.get("title", name)
            if not isinstance(title, str) or not 1 <= len(title) <= 80:
                raise DomainError(f"代码根目录 {name} 名称无效")
            roots[name] = {"name": name, "title": title, "path": resolved, "writable": writable}
        return roots

    @property
    def enabled(self) -> bool:
        return bool(self.config["enabled"] and self._roots)

    def path_for(self, name: str) -> dict:
        """按登记名取真实路径：接口用它把「根目录名」解析成目录，前端看不到路径。"""
        item = self._roots.get(name)
        if item is None:
            raise DomainError("代码工作区未登记或已撤销")
        return {"name": name, "path": str(item["path"]), "writable": item["writable"]}

    def roots(self) -> list[dict]:
        """只在管理员登记后暴露；不含绝对路径，避免泄漏服务器布局。"""
        return [{"name": item["name"], "title": item["title"], "writable": item["writable"]}
                for item in self._roots.values()]

    def _root(self, profile: dict) -> dict:
        name = (profile.get("workspace") or {}).get("root", "")
        if not name:
            raise DomainError("该 Agent 未绑定代码工作区")
        if not self.enabled:
            raise DomainError("代码工作区未启用")
        item = self._roots.get(name)
        if item is None:
            raise DomainError("代码工作区未登记或已撤销")
        return item

    def specs(self, profile: dict) -> dict:
        """只有绑定了根目录的 Agent 才看得到代码工具。"""
        item = self._root(profile)
        specs = {
            "code_tree": {"name": "code_tree", "read_only": True,
                "description": "列出代码工作区内的目录与文件；默认深度3，自动跳过依赖与缓存目录。",
                "input_schema": _schema({
                    "path": {"type": "string", "maxLength": 400},
                    "depth": {"type": "integer", "minimum": 1, "maximum": 4}}, [])},
            "code_read": {"name": "code_read", "read_only": True,
                "description": "按行读取文本文件；返回行数、总量与 sha256，写入前先用它确认内容。",
                "input_schema": _schema({
                    "path": {"type": "string", "minLength": 1, "maxLength": 400},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1}}, ["path"])},
            "code_search": {"name": "code_search", "read_only": True,
                "description": "在工作区内按文本或正则搜索，返回 路径:行号 与命中行。",
                "input_schema": _schema({
                    "pattern": {"type": "string", "minLength": 1, "maxLength": 200},
                    "path": {"type": "string", "maxLength": 400},
                    "regex": {"type": "boolean"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 200}},
                    ["pattern"])},
        }
        if item["writable"]:
            specs["code_patch"] = {"name": "code_patch", "read_only": False, "workspace_write": True,
                "description": "精确替换文件中的一段文本；old_string 必须唯一，返回差异与备份位置。",
                "input_schema": _schema({
                    "path": {"type": "string", "minLength": 1, "maxLength": 400},
                    "old_string": {"type": "string", "minLength": 1, "maxLength": 100_000},
                    "new_string": {"type": "string", "maxLength": 100_000},
                    "replace_all": {"type": "boolean"}},
                    ["path", "old_string", "new_string"])}
            specs["code_write"] = {"name": "code_write", "read_only": False, "workspace_write": True,
                "description": "新建或整体覆盖文本文件；覆盖已存在文件必须显式 overwrite。",
                "input_schema": _schema({
                    "path": {"type": "string", "minLength": 1, "maxLength": 400},
                    "content": {"type": "string", "maxLength": 100_000},
                    "overwrite": {"type": "boolean"},
                    "create_dirs": {"type": "boolean"}},
                    ["path", "content"])}
        if item["writable"] and self.shell["enabled"] and (profile.get("workspace") or {}).get("shell"):
            specs["code_shell"] = {"name": "code_shell", "read_only": False,
                "description": "在工作区内执行管理员白名单中的命令（如 pytest、ruff、git diff），返回退出码与输出。",
                "input_schema": _schema({
                    "argv": {"type": "array", "minItems": 1, "maxItems": 20,
                             "items": {"type": "string", "minLength": 1, "maxLength": 200}},
                    "cwd": {"type": "string", "maxLength": 400},
                    "timeout_s": {"type": "integer", "minimum": 1, "maximum": 600}},
                    ["argv"])}
        return specs

    def execute(self, name: str, arguments: dict, profile: dict) -> dict:
        """同步实现；调用方在线程池中执行，避免阻塞事件循环。"""
        item = self._root(profile)
        if name == "code_tree":
            return self._tree(item, arguments)
        if name == "code_read":
            return self._read(item, arguments)
        if name == "code_search":
            return self._search(item, arguments)
        if name in WRITE_TOOLS and not item["writable"]:
            raise DomainError("该代码工作区为只读")
        if name == "code_patch":
            return self._patch(item, arguments)
        if name == "code_write":
            return self._write(item, arguments)
        if name == "code_shell":
            return self._shell(item, arguments, profile)
        raise DomainError("代码工具不存在")

    def _resolve(self, item: dict, rel: object) -> Path:
        if not isinstance(rel, str) or len(rel) > 400:
            raise DomainError("路径必须是长度受限的文本")
        rel = rel.strip() or "."
        if rel.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", rel):
            raise DomainError("只接受工作区内的相对路径")
        root = item["path"]
        target = (root / rel).resolve()
        if target != root and root not in target.parents:
            raise DomainError("路径越界，已拒绝")
        return target

    def _relative(self, item: dict, target: Path) -> str:
        if target == item["path"]:
            return "."
        return target.relative_to(item["path"]).as_posix()

    def _check_readable(self, rel: str) -> None:
        normalized = rel.replace("\\", "/")
        if ".git/" in normalized or normalized.startswith(".git"):
            raise DomainError("版本库内部文件禁止读取")
        if "data/local" in normalized:
            raise DomainError("该路径存放私密数据，禁止读取")
        if SECRET_NAME.search(Path(normalized).name):
            raise DomainError("该文件可能包含密钥，禁止读取")

    def _check_writable(self, rel: str) -> None:
        parts = Path(rel).parts
        if ".git" in parts:
            raise DomainError("禁止写入 .git 目录")
        if SECRET_NAME.search(Path(rel).name):
            raise DomainError("禁止写入密钥类文件")

    def _tree(self, item: dict, arguments: dict) -> dict:
        base = self._resolve(item, arguments.get("path", ""))
        if not base.is_dir():
            raise DomainError("目录不存在")
        depth_limit = arguments.get("depth", 3)
        if type(depth_limit) is not int or not 1 <= depth_limit <= 4:
            raise DomainError("深度必须是 1–4 的整数")
        entries: list[dict] = []
        truncated = False
        base_depth = len(base.parts)
        for current, dirs, files in os.walk(base):
            here = Path(current)
            if len(here.parts) - base_depth >= depth_limit:
                dirs[:] = []
            dirs[:] = sorted(name for name in dirs if name not in self.ignore and not name.startswith("."))
            for name in sorted(files):
                if name == ".git" or SECRET_NAME.search(name):
                    continue
                path = here / name
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                entries.append({"path": path.relative_to(item["path"]).as_posix(),
                                "type": "file", "bytes": size})
                if len(entries) >= self.config["max_entries"]:
                    truncated = True
                    break
            if truncated:
                break
        return {"root": item["name"], "path": self._relative(item, base), "entries": entries,
                "truncated": truncated, "count": len(entries)}

    def _read_text(self, path: Path, limit: int) -> tuple[str, int, bool]:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise DomainError(f"读取失败：{exc.strerror or '未知错误'}") from exc
        digest = hashlib.sha256(raw).hexdigest()
        truncated = len(raw) > limit
        chunk = raw[:limit]
        if b"\x00" in chunk:
            raise DomainError("这是二进制文件，暂不支持读取")
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DomainError("文件不是 UTF-8 文本，暂不支持读取") from exc
        return text, digest, truncated

    def _read(self, item: dict, arguments: dict) -> dict:
        rel = arguments["path"]
        self._check_readable(rel)
        path = self._resolve(item, rel)
        if not path.is_file():
            raise DomainError("文件不存在")
        text, digest, truncated = self._read_text(path, self.config["max_read_bytes"])
        lines = text.splitlines()
        start = arguments.get("start_line", 1)
        end = arguments.get("end_line", len(lines))
        if type(start) is not int or type(end) is not int or start < 1 or end < start:
            raise DomainError("行号范围无效")
        chunk = "\n".join(lines[start - 1:end])[: self.config["max_output_chars"]]
        return {"path": self._relative(item, path), "sha256": digest, "total_lines": len(lines),
                "start_line": start, "end_line": min(end, len(lines)), "content": chunk,
                "truncated": truncated or min(end, len(lines)) < len(lines)}

    def _search(self, item: dict, arguments: dict) -> dict:
        base = self._resolve(item, arguments.get("path", ""))
        if not base.is_dir():
            raise DomainError("搜索目录不存在")
        pattern = arguments["pattern"]
        use_regex = arguments.get("regex", False)
        limit = arguments.get("max_results", 50)
        if type(limit) is not int or not 1 <= limit <= self.config["max_results"]:
            raise DomainError("结果数量超出限制")
        matcher = None
        if use_regex:
            try:
                matcher = re.compile(pattern)
            except re.error as exc:
                raise DomainError("正则表达式无效") from exc
        matches: list[dict] = []
        scanned = 0
        for current, dirs, files in os.walk(base):
            dirs[:] = sorted(name for name in dirs if name not in self.ignore and not name.startswith("."))
            for name in sorted(files):
                if SECRET_NAME.search(name):
                    continue
                path = Path(current) / name
                try:
                    if path.stat().st_size > self.config["max_scan_bytes"]:
                        continue
                    raw = path.read_bytes()
                except OSError:
                    continue
                if b"\x00" in raw[:2048]:
                    continue
                scanned += 1
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                for number, line in enumerate(text.splitlines(), start=1):
                    hit = matcher.search(line) if matcher else (pattern in line)
                    if not hit:
                        continue
                    matches.append({"path": path.relative_to(item["path"]).as_posix(),
                                    "line": number, "text": line.strip()[:300]})
                    if len(matches) >= limit:
                        return {"matches": matches, "truncated": True, "files_scanned": scanned}
        return {"matches": matches, "truncated": False, "files_scanned": scanned}

    def _backup(self, item: dict, path: Path) -> str | None:
        if not path.exists():
            return None
        relative = path.relative_to(item["path"])
        folder = self.project_root / "data/local/code-backups" / item["name"] / relative.parent
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{_now()}-{relative.name}.bak"
        target.write_bytes(path.read_bytes())
        return str(target.relative_to(self.project_root))

    def _replace(self, path: Path, content: str) -> None:
        if "\x00" in content:
            raise DomainError("只支持写入文本内容，不接受二进制数据")
        payload = content.encode("utf-8")
        if len(payload) > self.config["max_write_bytes"]:
            raise DomainError("写入内容超过单文件上限")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".code-tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)

    def _diff(self, old: str, new: str, rel: str) -> str:
        diff = difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                    fromfile="a/" + rel, tofile="b/" + rel, n=3)
        return "".join(diff)[: self.config["max_output_chars"]]

    def _patch(self, item: dict, arguments: dict) -> dict:
        rel = arguments["path"]
        self._check_writable(rel)
        path = self._resolve(item, rel)
        if not path.is_file():
            raise DomainError("文件不存在，请先用 code_write 新建")
        old_string, new_string = arguments["old_string"], arguments["new_string"]
        if len((old_string + new_string).encode("utf-8")) > self.config["max_patch_bytes"]:
            raise DomainError("替换内容超过上限")
        old_text, digest, truncated = self._read_text(path, self.config["max_write_bytes"])
        if truncated:
            raise DomainError("文件超过可编辑上限，请改用 code_write 分片重写")
        count = old_text.count(old_string)
        if count == 0:
            raise DomainError("未找到待替换文本，请先用 code_read 核对当前内容")
        if count > 1 and not arguments.get("replace_all"):
            raise DomainError(f"待替换文本出现 {count} 次，请提供更长的上下文或开启 replace_all")
        new_text = old_text.replace(old_string, new_string, -1 if arguments.get("replace_all") else 1)
        backup = self._backup(item, path)
        self._replace(path, new_text)
        return {"path": rel, "replaced": count if arguments.get("replace_all") else 1,
                "before_sha256": digest,
                "after_sha256": hashlib.sha256(new_text.encode()).hexdigest(),
                "backup": backup, "diff": self._diff(old_text, new_text, rel),
                "saved": True}

    def _write(self, item: dict, arguments: dict) -> dict:
        rel = arguments["path"]
        self._check_writable(rel)
        path = self._resolve(item, rel)
        content = arguments["content"]
        payload = content.encode("utf-8")
        if len(payload) > self.config["max_write_bytes"]:
            raise DomainError("写入内容超过单文件上限")
        exists = path.exists()
        if exists and not path.is_file():
            raise DomainError("目标路径已存在且不是文件")
        if exists and not arguments.get("overwrite"):
            raise DomainError("文件已存在；修改请用 code_patch，整体覆盖需显式 overwrite")
        if not exists and not arguments.get("create_dirs", True) and not path.parent.is_dir():
            raise DomainError("父目录不存在")
        old_text = ""
        if exists:
            old_text, _, _ = self._read_text(path, self.config["max_write_bytes"])
        backup = self._backup(item, path)
        self._replace(path, content)
        return {"path": rel, "created": not exists, "bytes": len(payload),
                "backup": backup, "diff": self._diff(old_text, content, rel) if exists else "",
                "saved": True}

    def _shell(self, item: dict, arguments: dict, profile: dict) -> dict:
        if not self.shell["enabled"]:
            raise DomainError("代码命令执行未启用")
        if not (profile.get("workspace") or {}).get("shell"):
            raise DomainError("该 Agent 未获准执行命令")
        argv = arguments["argv"]
        if (not isinstance(argv, list) or not 1 <= len(argv) <= 20
                or any(not isinstance(token, str) or not 1 <= len(token) <= 200
                       or "\n" in token or "\x00" in token for token in argv)):
            raise DomainError("命令参数必须是长度受限的字符串数组")
        command = " ".join(argv)
        allowed = [prefix for prefix in self.shell["allow"]
                   if command == prefix or command.startswith(prefix + " ")]
        if not allowed:
            raise DomainError("命令不在管理员允许列表")
        cwd = self._resolve(item, arguments.get("cwd", ""))
        if not cwd.is_dir():
            raise DomainError("工作目录不存在")
        timeout = arguments.get("timeout_s", self.shell["timeout_seconds"])
        if type(timeout) is not int or not 1 <= timeout <= 600:
            raise DomainError("超时必须是 1–600 秒")
        env = {key: value for key, value in os.environ.items() if not SECRET_ENV.search(key)}
        started = _iso()
        try:
            result = subprocess.run(argv, cwd=str(cwd), capture_output=True, timeout=timeout,
                                    shell=False, env=env, check=False)
        except subprocess.TimeoutExpired as exc:
            raise DomainError(f"命令超过 {timeout} 秒未结束，已终止") from exc
        except OSError as exc:
            raise DomainError(f"命令无法执行：{exc.strerror or '未知错误'}") from exc
        limit = self.config["max_output_chars"]
        stdout = result.stdout.decode("utf-8", "replace")
        stderr = result.stderr.decode("utf-8", "replace")
        return {"argv": argv, "started_at": started, "exit_code": result.returncode,
                "stdout": stdout[:limit], "stderr": stderr[:limit],
                "truncated": len(stdout) > limit or len(stderr) > limit}
