"""Outbound MCP client. Only server-admin configurations can launch/connect services."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import anyio

from rag_tech_retriever.domains.life_planning import DomainError


class ToolError(Exception):
    """Safe tool failure; do not return provider exceptions or credentials."""


class MCPGateway:
    """Short-lived SDK clients: close processes/connections on completion or timeout."""

    def __init__(self, root: Path, servers: dict, limits: dict,
                 env: Callable[..., str | None]) -> None:
        self.root, self.servers, self.limits, self.env = root, servers, limits, env

    def server(self, server_id: str) -> dict:
        cfg = self.servers.get(server_id)
        if not cfg or cfg.get("enabled") is not True or cfg.get("trusted") is not True:
            raise DomainError("MCP服务不存在、未启用或未经服务器管理员信任")
        return cfg

    def public(self) -> list[dict]:
        """Never reveal command arguments, headers, tokens, or credential references."""
        return [{"id": key, "transport": value.get("transport"),
                 "enabled": value.get("enabled") is True, "trusted": value.get("trusted") is True}
                for key, value in sorted(self.servers.items())]

    @asynccontextmanager
    async def _client(self, server_id: str):
        cfg = self.server(server_id)
        try:
            from mcp import Client, StdioServerParameters

            with anyio.fail_after(self.limits["timeout_seconds"]):
                if cfg.get("transport") == "stdio":
                    import os

                    target = StdioServerParameters(
                        command=cfg["command"], args=cfg.get("args", []), cwd=self.root,
                        env={key: str(self.env(ref, "")) for key, ref in cfg.get("env_refs", {}).items()},
                    )
                    # SDK stderr is redirected too: third-party subprocess logs may contain secrets.
                    from mcp.client.stdio import stdio_client

                    with await anyio.to_thread.run_sync(open, os.devnull, "w") as errors:
                        async with Client(stdio_client(target, errlog=errors),
                                          read_timeout_seconds=self.limits["timeout_seconds"]) as client:
                            yield client
                elif cfg.get("transport") == "streamable_http":
                    import httpx2
                    from mcp.client.streamable_http import streamable_http_client

                    url = cfg["url"]
                    parts = urlsplit(url)
                    if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username
                            or parts.password or parts.query or parts.fragment):
                        raise DomainError("MCP地址只能是无凭据或查询参数的HTTP(S)地址")
                    if parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
                        raise DomainError("远程MCP连接必须使用HTTPS")
                    headers = {key: str(self.env(ref, "")) for key, ref in cfg.get("headers_env", {}).items()}
                    async with (
                        httpx2.AsyncClient(headers=headers, follow_redirects=False, trust_env=False,
                                           timeout=self.limits["timeout_seconds"]) as http,
                        Client(streamable_http_client(url, http_client=http),
                               read_timeout_seconds=self.limits["timeout_seconds"]) as client,
                    ):
                        yield client
                else:
                    raise DomainError("MCP仅支持stdio或streamable_http")
        except (DomainError, ToolError):
            raise
        except Exception as exc:  # Sanitize SDK/transport exceptions, including ExceptionGroups.
            raise ToolError("MCP连接或调用失败，请检查服务配置、权限与超时") from exc

    @staticmethod
    def tool_name(server_id: str, remote: str) -> str:
        """Provider-compatible, collision-checked names up to 64 characters."""
        digest = hashlib.sha256((server_id + "\0" + remote).encode()).hexdigest()[:20]
        return "mcp_" + server_id[:35].replace("-", "_") + "_" + digest

    async def discover(self, server_id: str) -> list[dict]:
        """Bounded pagination; annotations are never treated as permission grants."""
        cfg, found, cursor = self.server(server_id), [], None
        async with self._client(server_id) as client:
            for _ in range(10):
                page = await client.list_tools(cursor=cursor)
                for tool in page.tools:
                    if tool.name in cfg.get("allow_tools", []):
                        found.append({"name": self.tool_name(server_id, tool.name),
                                      "description": (tool.description or tool.name)[:2000],
                                      "input_schema": tool.input_schema,
                                      "read_only": tool.name in cfg.get("readonly_tools", []),
                                      "server_id": server_id, "remote_name": tool.name})
                    if len(found) > self.limits["max_tools"]:
                        raise ToolError("MCP可用工具超过数量限制")
                if not page.next_cursor:
                    return found
                if page.next_cursor == cursor:
                    raise ToolError("MCP工具分页游标重复")
                cursor = page.next_cursor
        raise ToolError("MCP工具分页超过限制")

    async def call(self, spec: dict, arguments: dict) -> dict:
        """Recheck the server allowlist immediately before calling."""
        cfg = self.server(spec["server_id"])
        if spec["remote_name"] not in cfg.get("allow_tools", []):
            raise DomainError("MCP工具已被管理员撤销")
        async with self._client(spec["server_id"]) as client:
            result = await client.call_tool(spec["remote_name"], arguments)
            if result.is_error:
                raise ToolError("MCP工具执行失败，未将其视为成功")
            payload = {"content": [block.model_dump(mode="json", by_alias=True) for block in result.content],
                       "structured_content": result.structured_content}
            if len(json.dumps(payload, ensure_ascii=False)) > self.limits["max_result_chars"]:
                raise ToolError("MCP工具结果超过大小限制")
            return payload
