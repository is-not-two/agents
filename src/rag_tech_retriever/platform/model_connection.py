"""服务器私有模型连接；与知识、导出和源码快照分离。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.common.provider import (
    DEFAULT_CONTEXT_CHARS,
    ProviderError,
    post_chat,
    validate_provider_url,
)
from rag_tech_retriever.domains.life_planning import DomainError, text
from rag_tech_retriever.platform.record_store import StorageError, VersionConflict


def normalize_base(value: object) -> str:
    """HTTPS或回环HTTP；不含凭据/查询参数，兼容粘贴完整端点。"""
    value = text(value, "API 地址", 2048, True).rstrip("/")
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or any(ch.isspace() for ch in value)
        ):
            raise ValueError
        _ = parts.port
    except ValueError as exc:
        raise DomainError("请填写有效的 HTTP(S) API 地址，不要在地址中附带密钥或参数") from exc
    path = parts.path.removesuffix("/chat/completions")
    try:
        return validate_provider_url(urlunsplit((parts.scheme, parts.netloc, path, "", "")))
    except ProviderError as exc:
        raise DomainError(str(exc)) from exc


class ModelConnection:
    """网页配置优先；未保存过时读取环境变量/.env，密钥永不返回客户端。"""

    def __init__(self, path: Path, test_timeout: int = 12) -> None:
        self.path = path
        self.test_timeout = test_timeout
        self._mutex = threading.RLock()

    @contextmanager
    def _write_lock(self):
        """线程及同机多进程互斥，避免两个页面同时覆盖私有文件。"""
        with self._mutex:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix(".lock").open("a+b") as lock:
                if lock.seek(0, 2) == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    lock.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock, fcntl.LOCK_UN)

    def load(self) -> dict:
        """内部完整配置；调用方不得将返回值写入响应或日志。"""
        if self.path.is_file():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(saved, dict) or not all(
                    isinstance(saved.get(k), str)
                    for k in ("api_key", "base_url", "model", "revision")
                ):
                    raise ValueError
                return {**saved, "source": "web"}
            except (OSError, ValueError) as exc:
                raise StorageError("无法读取模型连接，请检查服务器私有配置文件") from exc
        cfg = ConfigLoader.load_default()
        key = str(cfg.env("LLM_API_KEY", "") or "")
        base = str(cfg.env("LLM_BASE_URL", "") or "")
        model = str(cfg.env("LLM_MODEL", "") or "")
        try:
            base = normalize_base(base) if base else ""
        except DomainError:
            base = ""
        source = "environment" if key or base or model else "none"
        return {
            "api_key": key,
            "base_url": base,
            "model": model,
            "revision": source,
            "source": source,
        }

    @staticmethod
    def public(config: dict) -> dict:
        """白名单投影，响应不包含密钥、片段或哈希。"""
        return {
            "base_url": config["base_url"],
            "model": config["model"],
            "revision": config["revision"],
            "source": config["source"],
            "has_api_key": bool(config["api_key"]),
            "configured": bool(config["api_key"] and config["base_url"] and config["model"]),
        }

    def prepare(self, payload: dict, current: dict | None = None) -> dict:
        """空密钥表示保留已存密钥；测试草稿与保存使用同一套规则。"""
        current = current or self.load()
        key = payload.get("api_key")
        key = text(key, "API 密钥", 8192) if key is not None else ""
        key = key or current["api_key"]
        if not key:
            raise DomainError("请填写 API 密钥")
        if any(ch.isspace() for ch in key):
            raise DomainError("API 密钥不能包含空格或换行")
        return {
            "base_url": normalize_base(payload.get("base_url", current["base_url"])),
            "model": text(payload.get("model", current["model"]), "模型名称", 160, True),
            "api_key": key,
        }

    def save(self, payload: dict) -> dict:
        """乐观版本检查与原子替换；保存后下一次生成立即读取。"""
        temporary = None
        try:
            with self._write_lock():
                current = self.load()
                if payload.get("revision") != current["revision"]:
                    raise VersionConflict("模型连接已被更新，请重新加载后再保存")
                config = {**self.prepare(payload, current), "revision": uuid4().hex}
                descriptor, temporary = tempfile.mkstemp(prefix=".llm-", dir=self.path.parent)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(config, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                return self.public({**config, "source": "web"})
        except OSError as exc:
            raise StorageError("无法保存模型连接，请检查服务器目录权限") from exc
        finally:
            if temporary and Path(temporary).exists():
                Path(temporary).unlink()

    def test(self, payload: dict) -> dict:
        """发送一次短请求验证当前输入，不保存；不回传供应商正文或密钥。"""
        current = self.load()
        if "revision" in payload and payload["revision"] != current["revision"]:
            raise VersionConflict("模型连接已被更新，请重新加载后再测试")
        config = self.prepare(payload, current)
        body = {"model": config["model"], "messages": [{"role": "user", "content": "Reply OK."}],
                "max_tokens": 8, "stream": False}
        try:
            envelope = post_chat(config, body, self.test_timeout, DEFAULT_CONTEXT_CHARS)
            content = envelope["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError
        except ProviderError as exc:
            messages = {401: "密钥无效或已失效", 403: "此密钥没有访问权限",
                        404: "API 地址或模型名称不正确", 429: "请求受限或余额不足，请检查服务商账户"}
            return {"ok": False, "message": messages.get(exc.status, "无法连接模型服务或响应无效，请检查配置")}
        except (ValueError, KeyError, IndexError, TypeError):
            return {"ok": False, "message": "服务响应不符合聊天接口格式，请检查 API 地址和模型"}
        return {"ok": True, "message": "连接成功，模型已返回有效回复"}
