"""Shared MCP registration/limit policy for runtime and redacted release diagnostics."""

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.life_planning import DomainError

BUSINESS_TOOLS = {"jobs_search", "jobs_weekly_stats", "learning_due"}
KNOWN_TOOLS = BUSINESS_TOOLS | {"protocol_query", "stacktrace_parser", "debug_retriever", "search_docs", "knowledge_search"}
DEFAULT_LIMITS = {"default_limit": 20, "max_limit": 50, "max_offset": 10000,
                  "max_query_chars": 200, "max_title_chars": 240,
                  "statement_timeout_ms": 3000, "max_stats_records": 5000, "max_stats_versions": 20000}


def query_limits(value: dict | None) -> dict:
    """Only administrator-owned bounded integers may control query resources."""
    if value is None: value = {}
    if not isinstance(value, dict) or set(value) - DEFAULT_LIMITS.keys():
        raise DomainError("MCP查询限额字段无效")
    limits = {**DEFAULT_LIMITS, **value}
    ceilings = {"default_limit": 100, "max_limit": 100, "max_offset": 10000,
                "max_query_chars": 1000, "max_title_chars": 1000, "statement_timeout_ms": 10000,
                "max_stats_records": 100000, "max_stats_versions": 100000}
    if any(type(v) is not int or not 1 <= v <= ceilings[key] for key, v in limits.items()) or limits["default_limit"] > limits["max_limit"]:
        raise DomainError("MCP查询限额必须是有效整数，默认条数不能超过上限")
    return limits


def validate_mcp_config(config: ConfigLoader) -> None:
    """Readonly metadata never grants a missing capability or silently coerces a flag."""
    for field, default in (("permissions.readonly", True), ("permissions.admin", False), ("resources.corpus.enabled", False)):
        if type(config.get(field, default)) is not bool: raise DomainError("MCP开关必须是布尔值")
    if config.get("permissions.admin", False): raise DomainError("此MCP服务不支持管理或写入权限")
    tools = config.get("tools", {})
    if not isinstance(tools, dict): raise DomainError("MCP工具配置必须是映射")
    for name, item in tools.items():
        if not isinstance(item, dict) or type(item.get("enabled", False)) is not bool:
            raise DomainError("MCP工具开关必须是布尔值")
        if item.get("enabled") and (name not in KNOWN_TOOLS or item.get("permission", "readonly") != "readonly"):
            raise DomainError("MCP只允许已实现的只读白名单工具")
    query_limits(config.get("query_limits", {}))


def business_enabled(config: ConfigLoader) -> bool:
    """Switches are validated separately; disabled readonly access exposes no tools."""
    return config.get("permissions.readonly", True) is True and any(
        config.get(f"tools.{name}.enabled", False) is True for name in BUSINESS_TOOLS)
