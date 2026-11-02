"""MCP 协议端点（官方 SDK 2.x）：把只读原子工具与语料资源按 MCP 标准对外暴露。

- 组装：build_mcp_server(search, mcp_config) 返回 MCPServer 实例（可独立运行，也可挂载）
- 挂载：streamable_app() 产 ASGI 应用，由 api.main 挂到 /mcp（Streamable HTTP 传输）
- 工具：mcp.yaml 的 tools.*.enabled 控制，全部只读；不暴露任何写入类操作
- 资源：rag://corpus/chunks —— 技术语料清单（构建时快照，只读）
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError
from mcp.types import ToolAnnotations
from pydantic import StrictInt

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.corpus_catalog import CorpusCatalog
from rag_tech_retriever.platform.mcp_policy import validate_mcp_config
from rag_tech_retriever.platform.mcp_queries import BusinessQueries
from rag_tech_retriever.platform.record_store import StorageError
from rag_tech_retriever.rag.vector_store.schema import validate_table_name
from rag_tech_retriever.tools.debug_retriever import create_debug_retriever
from rag_tech_retriever.tools.protocol_query import protocol_query as query_protocol
from rag_tech_retriever.tools.stacktrace_parser import parse_stacktrace

_TOOL_DESCRIPTIONS = {
    "protocol_query": "按协议号在技术文档语料中精准/包含匹配，返回 chunk 定位与摘要（只读）",
    "stacktrace_parser": "解析 Python/JavaScript 异常栈，返回错误类型、帧列表、可能原因与排查方向（纯文本）",
    "debug_retriever": "检索调试：返回命中列表、实际引擎与降级说明（只读，30 秒缓存）",
    "search_docs": "技术文档/个人知识检索入口：scope=all|personal|docs|planning（只读，不生成）",
    "knowledge_search": "知识查询；namespace受服务器白名单约束，只读且不调用模型。",
    "jobs_search": "按公司/岗位/状态查询有效投递摘要，不含JD原文、备注、简历或面试回答。",
    "jobs_weekly_stats": "查询指定日期所属周的真实统计，不生成、不冻结、不发送周报。",
    "learning_due": "查询服务器当前已到期的复习卡标题和时间；不含答案、不记录复习。",
}


class ReadonlyMCPServer(MCPServer):
    """Use public SDK extension points; unknown input fields cannot be silently ignored."""

    async def list_tools(self) -> list:
        tools = await super().list_tools()
        return [tool.model_copy(update={"input_schema": {**tool.input_schema, "additionalProperties": False}}) for tool in tools]

    async def call_tool(self, name: str, arguments: dict, context: Any = None) -> Any:
        tool = next((item for item in await self.list_tools() if item.name == name), None)
        if tool and (not isinstance(arguments, dict) or set(arguments) - tool.input_schema.get("properties", {}).keys()):
            raise MCPToolError("工具参数包含未允许字段")
        return await super().call_tool(name, arguments, context)


def _load_mcp_config() -> ConfigLoader:
    settings = ConfigLoader.load_default()
    return ConfigLoader(settings.settings_path.parent / "mcp.yaml")


def build_mcp_server(search, mcp_config: ConfigLoader | None = None) -> MCPServer:
    """按 mcp.yaml 组装只读 MCP 服务；search 为 SearchService 实例。"""
    config = mcp_config if mcp_config is not None else _load_mcp_config()
    validate_mcp_config(config)
    catalog = getattr(search, "catalog", None) or CorpusCatalog()
    server = ReadonlyMCPServer(
        name=str(config.get("server.name", "rag-tech-doc-retriever")),
        description="时列工作台只读工具与语料资源（MCP Streamable HTTP）",
    )

    def search_docs(query: str, scope: str = "docs", mode: str = "text", namespace: str | None = None) -> dict:
        if scope not in {"all", "personal", "docs", "planning"}:
            raise ValueError("scope 取值不合法")
        if mode not in {"text", "vector"}:
            raise ValueError("mode 取值不合法")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query 不能为空")
        try:
            catalog.select(namespace)
            return search.query(" ".join(query.split()), scope, mode, False) if namespace is None else search.query(" ".join(query.split()), scope, mode, False, namespace)
        except DomainError as exc:
            raise MCPToolError(str(exc)) from None

    def protocol_query(number: str, limit: int = 5, namespace: str | None = None) -> dict:
        # Table names are administrator-owned, never MCP input. The low-level
        # Python helper remains available to trusted experiment scripts.
        table = validate_table_name(str(ConfigLoader.load_default().get("vector_store.table_name", "rag_chunks")))
        try:
            return query_protocol(number, limit, table, catalog.select(namespace))
        except DomainError as exc:
            raise MCPToolError(str(exc)) from None
        except RuntimeError:
            raise MCPToolError("语料库暂不可用") from None

    debug_retriever = create_debug_retriever(search)
    queries_instance = None

    def queries() -> BusinessQueries:
        nonlocal queries_instance
        if queries_instance is None:
            queries_instance = BusinessQueries(search.store, catalog.root, search.connection, config.get("query_limits", {}))
        return queries_instance

    def business_call(method: str, **arguments: Any) -> dict:
        try:
            return getattr(queries(), method)(**arguments)
        except DomainError as exc:
            raise MCPToolError(str(exc)) from None
        except StorageError:
            raise MCPToolError("业务数据库暂不可用；未返回伪造或缓存统计") from None

    def jobs_search(company: str = "", position: str = "", status: str = "", limit: StrictInt | None = None, offset: StrictInt = 0) -> dict:
        return business_call("jobs_search", company=company, position=position, status=status, limit=limit, offset=offset)

    def jobs_weekly_stats(day: str = "") -> dict:
        return business_call("jobs_weekly_stats", day=day)

    def learning_due(limit: StrictInt | None = None, offset: StrictInt = 0) -> dict:
        return business_call("learning_due", limit=limit, offset=offset)
    available = {
        "protocol_query": protocol_query,
        "stacktrace_parser": parse_stacktrace,
        "debug_retriever": debug_retriever,
        "search_docs": search_docs,
        "knowledge_search": search_docs,
        "jobs_search": jobs_search,
        "jobs_weekly_stats": jobs_weekly_stats,
        "learning_due": learning_due,
    }
    for name, fn in available.items():
        if config.get("permissions.readonly", True) and config.get(f"tools.{name}.enabled", False):
            server.add_tool(fn, name=name, description=_TOOL_DESCRIPTIONS[name], annotations=ToolAnnotations(
                read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False))

    if config.get("permissions.readonly", True) and config.get("resources.corpus.enabled", False):
        server.add_resource(_corpus_resource(catalog))
    return server


def _corpus_resource(catalog: CorpusCatalog | None = None):
    """rag://corpus/chunks：语料清单快照（构建时生成；库不可用时明确标注）。"""
    from mcp.types import Resource

    namespace = (catalog or CorpusCatalog()).select(None)

    try:
        from rag_tech_retriever.rag.vector_store.pgvector_client import (
            PgVectorClient,
            VectorStoreError,
        )

        table = validate_table_name(str(
            ConfigLoader.load_default().get("vector_store.table_name", "rag_chunks")
        ))
        client = PgVectorClient()
        try:
            client.connect()
            total = client.count(table, namespace)
            sample = client.fetch_all(
                f"SELECT chunk_id, heading_path FROM {table} "
                "WHERE namespace=%s ORDER BY chunk_id LIMIT 20", (namespace,)
            )
        finally:
            client.close()
        body = {
            "namespace": namespace,
            "total_chunks": total,
            "sample": sample,
        }
    except (VectorStoreError, OSError, ValueError):
        # 语料库属可选依赖：降级标注，不冒充可用
        body = {"namespace": namespace, "available": False, "reason": "语料库暂不可用"}
    return Resource(
        uri="rag://corpus/chunks",
        name="技术语料 chunk 清单",
        mimeType="application/json",
        text=json.dumps(body, ensure_ascii=False),
    )


def streamable_app(search, mcp_config: ConfigLoader | None = None):
    """返回可挂载到 FastAPI 的 Streamable HTTP ASGI 应用。

    SDK 默认内部路由自带 /mcp 前缀；这里改为根路径，由挂载方提供 /mcp 前缀，
    避免出现 /mcp/mcp 双前缀。
    传输安全按部署形态（用户口径：服务器一般使用 HTTP，无 TLS）：
    - mcp.yaml server.allowed_hosts 非空 → 启用 Host 头校验（防 DNS 重绑定），
      适用于 HTTP 公网/内网暴露；
    - 留空（默认）→ 关闭该校验，鉴权由宿主令牌中间件承担
      （SDK 对 localhost 自动启用的默认校验会误伤测试客户端与代理，显式关闭）。
    """
    from mcp.server.transport_security import TransportSecuritySettings

    config = mcp_config if mcp_config is not None else _load_mcp_config()
    allowed_hosts = [str(h) for h in (config.get("server.allowed_hosts", []) or [])]
    security = (
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts
        )
        if allowed_hosts
        else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    return build_mcp_server(search, config).streamable_http_app(
        streamable_http_path="/",
        transport_security=security,
    )


def create_router(context) -> APIRouter:
    """状态端点：暴露 MCP 服务配置摘要（实际协议端点挂在 /mcp，不走本路由）。"""
    router = APIRouter(prefix="/api/mcp", tags=["mcp"])
    config = _load_mcp_config()

    @router.get("/status")
    def status() -> dict:
        tools_cfg = config.get("tools", {}) or {}
        return {
            "server": str(config.get("server.name", "")),
            "transport": "streamable-http",
            "mount": "/mcp",
            "tools": [
                {
                    "name": name,
                    "enabled": config.get("permissions.readonly", True) and cfg.get("enabled", False),
                    "configured_enabled": cfg.get("enabled", False),
                    "permission": cfg.get("permission", "readonly"),
                }
                for name, cfg in tools_cfg.items()
                if isinstance(cfg, dict)
            ],
            "resource": {
                "uri": "rag://corpus/chunks",
                "enabled": config.get("permissions.readonly", True) and config.get("resources.corpus.enabled", False),
            },
            "readonly_only": True,
            "business_queries_opt_in": True,
        }

    return router
