"""Admin-defined HTTP JSON tools with fixed hosts and strict schema validation.

Only server administrators can add manifests. Request bodies can never choose a
URL, host, method, or header; values are substituted into a fixed template.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, build_opener

from jsonschema import Draft202012Validator

from rag_tech_retriever.domains.life_planning import DomainError

MAX_RESPONSE_BYTES = 1_048_576
NAME = re.compile(r"[a-z][a-z0-9_-]{0,40}\Z")
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_-]{0,40})\}")


class HttpToolError(Exception):
    """Safe failure without URLs containing secrets or provider bodies."""


class _NoRedirect:
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def is_private_host(host: str) -> bool:
    """Reject loopback and obvious private address literals, including DNS tricks."""
    host = host.lower().strip("[]")
    if host in {"localhost", "localhost.localdomain", "::1", "0.0.0.0"}:
        return True
    if host.endswith((".local", ".internal")):
        return True
    parts = host.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        first, second = int(parts[0]), int(parts[1])
        return first in {10, 127} or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168) or first == 169
    return False


class HttpToolGateway:
    """One manifest = one fixed endpoint; all calls are auditable and bounded."""

    def __init__(self, manifests: dict | None, limits: dict, env: Callable[..., str | None]) -> None:
        self.manifests = manifests or {}
        if not isinstance(self.manifests, dict):
            raise DomainError("http_tools 配置必须为对象")
        self.limits, self.env = limits, env
        self.tools: dict[str, dict] = {}
        for key, raw in self.manifests.items():
            self.tools[self._name(key)] = self._validate(key, raw)

    @staticmethod
    def _name(tool_id: str) -> str:
        if not isinstance(tool_id, str) or not NAME.fullmatch(tool_id):
            raise DomainError("HTTP 工具标识只允许小写字母、数字、_ 或 -")
        return "http_" + tool_id

    def _validate(self, tool_id: str, raw: object) -> dict:
        if not isinstance(raw, dict):
            raise DomainError("HTTP 工具配置必须为对象")
        allowed = {"description", "url", "method", "query", "body", "headers_env", "read_only",
                   "timeout_seconds", "input_schema"}
        if set(raw) - allowed:
            raise DomainError("HTTP 工具配置包含未知字段")
        description = raw.get("description")
        if not isinstance(description, str) or not 1 <= len(description) <= 2000:
            raise DomainError("HTTP 工具描述必须为 1–2000 字")
        method = raw.get("method", "GET")
        if method not in {"GET", "POST"}:
            raise DomainError("HTTP 工具只支持 GET 或 POST")
        url = raw.get("url")
        if not isinstance(url, str):
            raise DomainError("HTTP 工具 URL 缺失")
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or is_private_host(parts.hostname)):
            raise DomainError("HTTP 工具只允许不含凭据/查询/片段的 HTTPS 公网地址")
        headers_env = raw.get("headers_env", {})
        if not isinstance(headers_env, dict) or len(headers_env) > 10 or any(
            not isinstance(k, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", k)
            or not isinstance(v, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", v)
            for k, v in headers_env.items()
        ):
            raise DomainError("HTTP 工具请求头必须引用环境变量名")
        schema = raw.get("input_schema")
        if not isinstance(schema, dict):
            raise DomainError("HTTP 工具必须提供 input_schema")
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            raise DomainError("HTTP 工具 input_schema 不受支持") from exc
        for field in ("query", "body"):
            template = raw.get(field, {})
            if not isinstance(template, dict) or len(template) > 30:
                raise DomainError(f"HTTP 工具 {field} 模板格式错误")
            for key, value in template.items():
                if not isinstance(key, str) or not isinstance(value, str) or len(value) > 200:
                    raise DomainError(f"HTTP 工具 {field} 模板条目必须是短文本")
                if any(not PLACEHOLDER.fullmatch("{" + name + "}") for name in PLACEHOLDER.findall(value)):
                    raise DomainError("HTTP 工具模板占位符格式错误")
        timeout = raw.get("timeout_seconds", min(self.limits["timeout_seconds"], 20))
        if type(timeout) is not int or not 3 <= timeout <= 30:
            raise DomainError("HTTP 工具超时必须在 3–30 秒")
        read_only = raw.get("read_only", True)
        if not isinstance(read_only, bool):
            raise DomainError("HTTP 工具 read_only 必须为布尔值")
        return {"id": tool_id, "name": "http_" + tool_id, "description": description,
                "url": url, "method": method, "query": raw.get("query", {}), "body": raw.get("body", {}),
                "headers_env": headers_env, "read_only": read_only, "timeout_seconds": timeout,
                "input_schema": schema}

    def specs(self, tool_ids: list[str]) -> dict:
        result = {}
        for name, tool in self.tools.items():
            if name not in tool_ids:
                continue
            result[name] = {"name": name, "description": tool["description"],
                            "input_schema": tool["input_schema"], "read_only": tool["read_only"],
                            "http_tool": tool["id"]}
        return result

    def public(self) -> list[dict]:
        """No URL, header values, or environment variable names are exposed."""
        return [{"id": tool["id"], "name": tool["name"], "description": tool["description"],
                 "read_only": tool["read_only"], "timeout_seconds": tool["timeout_seconds"]}
                for tool in sorted(self.tools.values(), key=lambda item: item["id"])]

    @staticmethod
    def _render(template: dict, arguments: dict) -> dict:
        """Substitute schema values into fixed templates; encoding happens once."""
        rendered = {}
        for key, value in template.items():
            for placeholder in PLACEHOLDER.findall(value):
                if placeholder not in arguments:
                    raise DomainError("HTTP 工具参数缺少模板占位值")
                supplied = arguments[placeholder]
                if not isinstance(supplied, (str, int, float)) or isinstance(supplied, bool):
                    raise DomainError("HTTP 工具模板值必须是文本或数字")
                value = value.replace("{" + placeholder + "}", str(supplied))
            rendered[key] = value
        return rendered

    def call(self, spec: dict, arguments: dict) -> dict:
        tool = next((item for item in self.tools.values() if item["id"] == spec.get("http_tool")), None)
        if tool is None:
            raise DomainError("HTTP 工具不存在或已被撤销")
        try:
            Draft202012Validator(tool["input_schema"]).validate(arguments)
        except Exception as exc:
            raise DomainError("HTTP 工具参数不符合 Schema") from exc
        query = self._render(tool["query"], arguments)
        body = self._render(tool["body"], arguments)
        parts = urlsplit(tool["url"])
        final = urlunsplit((parts.scheme, parts.netloc, parts.path,
                            "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in query.items()), ""))
        headers = {"User-Agent": "ShilieTools/1.0", "Accept": "application/json"}
        headers.update({key: str(self.env(ref, "")) for key, ref in tool["headers_env"].items()})
        data = None
        if tool["method"] == "POST":
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = Request(final, data=data, headers=headers)
        raw, content_type = self._fetch(request, tool["timeout_seconds"])
        if len(raw) > MAX_RESPONSE_BYTES:
            raise HttpToolError("HTTP 工具响应超过大小限制")
        text = raw.decode("utf-8", "replace")
        if "application/json" in content_type:
            try:
                return {"status": "ok", "json": json.loads(text)}
            except json.JSONDecodeError as exc:
                raise HttpToolError("HTTP 工具返回了无效 JSON") from exc
        return {"status": "ok", "text": text[:16000]}

    def _fetch(self, request: Request, timeout: int) -> tuple[bytes, str]:
        """Single fixed-endpoint request; extracted for deterministic tests."""
        try:
            with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
                return response.read(MAX_RESPONSE_BYTES + 1), response.headers.get("Content-Type", "")
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise HttpToolError("HTTP 工具服务不可达、超时或被拒绝") from exc
