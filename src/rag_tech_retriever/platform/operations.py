"""Read-only operational diagnostics and explicit deployment-profile validation."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from rag_tech_retriever.common.config_loader import ConfigError, ConfigLoader, load_yaml_mapping
from rag_tech_retriever.common.schema_policy import resolve_schema_mode, schema_timeouts
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.mcp_policy import business_enabled, validate_mcp_config


def configuration_report(
    root: Path, profile: str | None = None,
    env: Callable[[str, str], str | None] | None = None,
) -> dict[str, Any]:
    """Return public check results only; never include environment values or YAML values."""
    checks: list[dict[str, str]] = []

    def add(key: str, status: str, message: str) -> None:
        checks.append({"id": key, "status": status, "message": message})

    loaded = {}
    for name in ["settings", "web", "prompts", "mcp", "agent-tools"]:
        try:
            loaded[name] = load_yaml_mapping(root / "config" / (name + ".yaml"))
            add("yaml_" + name, "pass", name + " 配置格式通过")
        except ConfigError:
            add("yaml_" + name, "fail", name + " 配置缺失、重复键或格式错误")
    if env is None:
        try:
            settings = ConfigLoader(root / "config/settings.yaml", root / ".env")
            env = settings.env
        except ConfigError:
            env = lambda key, default: default
    web = loaded.get("web", {}).get("web", {})
    ops = loaded.get("web", {}).get("operations", {})
    if not isinstance(web, dict):
        web = {}
    if not isinstance(ops, dict):
        ops = {}
    selected = profile or str(env("WORKSPACE_PROFILE", str(ops.get("profile", "local"))))
    add("profile", "pass" if selected in {"local", "production"} else "fail",
        "部署模式有效" if selected in {"local", "production"} else "部署模式必须为 local/production")
    try:
        mode = resolve_schema_mode(selected, str(env("WORKSPACE_SCHEMA_MODE", "") or ""))
        add("schema_mode", "pass", "结构策略：" + mode + "；生产不执行启动DDL")
    except ConfigError:
        add("schema_mode", "fail", "结构策略无效；生产只允许verify")
    try:
        schema_timeouts(ConfigLoader(root / "config/settings.yaml", root / ".env"))
        add("schema_timeouts", "pass", "结构核验与管理员迁移有界超时")
    except ConfigError:
        add("schema_timeouts", "fail", "结构核验或管理员迁移超时无效")
    for key, low, high in [("port", 1, 65535), ("max_body_bytes", 1, 1073741824),
                            ("session_hours", 1, 168), ("rate_limit_per_minute", 0, 1000000)]:
        value = web.get(key)
        ok = isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
        add("web_" + key, "pass" if ok else "fail", key + (" 范围有效" if ok else " 类型或范围无效"))
    timeout = ops.get("readiness_timeout_seconds", 3)
    valid_timeout = isinstance(timeout, int) and not isinstance(timeout, bool) and 2 <= timeout <= 10
    add("readiness_timeout", "pass" if valid_timeout else "fail", "就绪探针超时配置" + ("有效" if valid_timeout else "无效"))
    token = str(env("WORKSPACE_ACCESS_TOKEN", "") or "")
    mcp_token = str(env("WORKSPACE_MCP_TOKEN", "") or "")
    try:
        mcp_config = ConfigLoader(root / "config/mcp.yaml", root / ".env")
        validate_mcp_config(mcp_config)
        add("mcp_policy", "pass", "MCP仅注册明确启用的只读工具")
        valid = (not mcp_token or (len(mcp_token) >= 32 and mcp_token == mcp_token.strip() and mcp_token != token)) and (not business_enabled(mcp_config) or bool(mcp_token))
        add("mcp_credential", "pass" if valid else "fail", "业务MCP需独立32位以上令牌，且不得与工作台令牌相同")
    except (ConfigError, DomainError):
        add("mcp_policy", "fail", "MCP只读策略或查询限额无效")
    required = str(env("WORKSPACE_REQUIRE_AUTH", "false")).lower() == "true"
    password = str(env("POSTGRES_PASSWORD", "") or "")
    if selected == "production":
        add("authentication", "pass" if required and len(token) >= 32 else "fail", "生产模式必须显式启用鉴权并配置至少 32 字符访问令牌")
        add("database_secret", "pass" if len(password) >= 16 and password != "change_me" else "fail", "生产模式必须配置至少 16 字符的非示例数据库口令")
        raw_rate = str(env("WEB_RATE_LIMIT_PER_MINUTE", str(web.get("rate_limit_per_minute", ""))))
        add("production_rate_limit", "pass" if raw_rate.isdigit() and int(raw_rate) > 0 else "fail", "生产模式必须启用限流")
    else:
        add("authentication", "pass" if token else "warn", "已配置访问令牌" if token else "本地无令牌模式，仅用于回环或受控环境")
    return {"profile": selected if selected in {"local", "production"} else "invalid", "passed": not any(c["status"] == "fail" for c in checks),
            "checks": checks}
