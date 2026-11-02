"""Skills and tools registry, independent of model providers and HTTP routes."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import anyio
import yaml
from jsonschema import Draft202012Validator, SchemaError, ValidationError

from rag_tech_retriever.domains.knowledge import validate_knowledge
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.github_skills import GitHubSkills
from rag_tech_retriever.platform.mcp_client import MCPGateway, ToolError
from rag_tech_retriever.platform.record_store import RecordMissing, RecordStore
from rag_tech_retriever.platform.search_service import SearchService
from rag_tech_retriever.platform.skill_registry import SkillRegistry, valid_name

DEFAULT_LIMITS = {"max_steps": 6, "max_calls": 12, "max_tools": 32, "timeout_seconds": 30,
                  "max_result_chars": 16000, "max_skill_bytes": 65536, "max_tokens": 1500,
                  "run_timeout_seconds": 120, "max_context_chars": 120000,
                  "max_memory_items": 50, "max_memory_chars": 2000,
                  "max_memory_context_chars": 12000, "max_session_turns": 20, "max_evidence_chars": 3000}


def object_schema(properties: dict, required: list[str]) -> dict:
    """All builtins reject unknown arguments rather than silently ignoring them."""
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


BUILTINS = {
    "knowledge_search": {"description": "检索当前Agent获准访问的知识/技术文档/规划，返回引用。",
        "input_schema": object_schema({"query": {"type": "string", "minLength": 1, "maxLength": 1000},
                                       "scope": {"type": "string", "enum": ["personal", "docs", "planning"]}}, ["query", "scope"])},
    "knowledge_get": {"description": "按ID读取个人知识；不能读取私密日记或愿望。",
        "input_schema": object_schema({"id": {"type": "string", "minLength": 1, "maxLength": 100}}, ["id"])},
    "planning_get": {"description": "按ID读取人生规划。",
        "input_schema": object_schema({"id": {"type": "string", "minLength": 1, "maxLength": 100}}, ["id"])},
    "knowledge_draft": {"description": "生成待人工保存的知识草稿，不写入数据库。",
        "input_schema": object_schema({"title": {"type": "string", "minLength": 1, "maxLength": 160},
                                       "content": {"type": "string", "maxLength": 10000}}, ["title", "content"])},
}


def validate_schema(schema: dict) -> None:
    """Never fetch a remote JSON Schema reference supplied by an MCP server."""
    if not isinstance(schema, dict) or len(json.dumps(schema)) > 16000:
        raise ToolError("工具参数Schema格式不正确或过大")

    def walk(item):
        if isinstance(item, dict):
            for key, value in item.items():
                if key in {"$ref", "$dynamicRef"} and (not isinstance(value, str) or not value.startswith("#")):
                    raise ToolError("工具Schema禁止引用外部地址")
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    try:
        walk(schema)
        Draft202012Validator.check_schema(schema)
    except (SchemaError, RecursionError) as exc:
        raise ToolError("工具参数Schema不受支持") from exc


class CapabilityService:
    """Explicit per-agent grants; a skill cannot grant new tool permissions."""

    def __init__(self, root: Path, store: RecordStore, search: SearchService,
                 env: Callable[..., str | None]) -> None:
        path = root / "config/agent-tools.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        config = config or {}
        if not isinstance(config, dict):
            raise DomainError("Agent工具配置必须为YAML对象")
        self.limits = {**DEFAULT_LIMITS, **config.get("limits", {})}
        self.model_aliases = config.get("model_aliases", {})
        if (not isinstance(self.model_aliases, dict) or any(
            not valid_name(key) or not isinstance(value, str) or not 1 <= len(value) <= 200
            for key, value in self.model_aliases.items()
        )):
            raise DomainError("模型别名必须是管理员配置的名称映射，不接受连接或密钥")
        if any(type(value) is not int or not 1 <= value <= 1000000 for value in self.limits.values()):
            raise DomainError("Agent限制配置必须为正整数")
        directory = (root / config.get("skills_dir", "data/local/skills")).resolve()
        if not directory.is_relative_to(root.resolve()):
            raise DomainError("技能目录必须位于项目内")
        self.skills = SkillRegistry(directory, self.limits["max_skill_bytes"])
        self.github = GitHubSkills(root / "data/local/skill-imports", self.skills, config.get("github", {}))
        servers = config.get("servers", {})
        if not isinstance(servers, dict) or any(not valid_name(key) or not isinstance(value, dict) for key, value in servers.items()):
            raise DomainError("MCP服务配置标识或格式不正确")
        self.mcp = MCPGateway(root, servers, self.limits, env)
        self.store, self.search = store, search

    def validate_binding(self, profile: dict) -> dict:
        """Validate local references without contacting an external service on save."""
        alias = profile.get("model", {}).get("alias", "")
        if alias and alias not in self.model_aliases:
            raise DomainError("模型别名未在服务器登记")
        for name in profile.get("skill_ids", []):
            self.skills.get(name)
        unknown = set(profile.get("tool_ids", [])) - BUILTINS.keys()
        if any(not name.startswith("mcp_") for name in unknown):
            raise DomainError("Agent包含不存在的内置工具")
        if unknown and not profile.get("mcp_server_ids"):
            raise DomainError("MCP工具必须同时绑定所属服务")
        for server in profile.get("mcp_server_ids", []):
            if not valid_name(server):
                raise DomainError("MCP服务标识格式不正确")
            self.mcp.server(server)
        return profile

    async def catalog(self, profile: dict) -> tuple[dict, list[dict]]:
        self.validate_binding(profile)
        specs = {name: {"name": name, **BUILTINS[name], "read_only": True}
                 for name in profile.get("tool_ids", []) if name in BUILTINS}
        skills = [self.skills.get(name) for name in profile.get("skill_ids", [])]
        if skills:
            specs["activate_skill"] = {"name": "activate_skill", "description": "按需读取获准技能的操作说明，不执行脚本。",
                "input_schema": object_schema({"name": {"type": "string", "enum": [s["name"] for s in skills]}}, ["name"]),
                "read_only": True}
        for server in profile.get("mcp_server_ids", []):
            for spec in await self.mcp.discover(server):
                if spec["name"] not in profile.get("tool_ids", []):
                    continue
                if spec["name"] in specs:
                    raise ToolError("工具名称冲突")
                specs[spec["name"]] = spec
        if set(profile.get("tool_ids", [])) - specs.keys():
            raise ToolError("已授权的工具不存在、已撤销或不在服务器允许列表中")
        if len(specs) > self.limits["max_tools"]:
            raise ToolError("Agent工具数量超过限制")
        for spec in specs.values():
            validate_schema(spec["input_schema"])
        return specs, skills

    async def execute(self, spec: dict, arguments: dict, profile: dict, skills: list[dict],
                      approved: bool = False) -> dict:
        """Every call checks schema and current grants, even after model selection."""
        validate_schema(spec["input_schema"])
        try:
            Draft202012Validator(spec["input_schema"]).validate(arguments)
        except (ValidationError, RecursionError) as exc:
            raise DomainError("工具参数不符合Schema") from exc
        if not spec["read_only"] and not approved:
            raise DomainError("该工具需要人工确认")
        name = spec["name"]
        if "server_id" in spec:
            if (spec["server_id"] not in profile.get("mcp_server_ids", [])
                    or name not in profile.get("tool_ids", [])):
                raise DomainError("Agent无权使用该MCP服务")
            return await self.mcp.call(spec, arguments)
        if name == "activate_skill":
            if arguments["name"] not in profile.get("skill_ids", []):
                raise DomainError("Agent无权加载该技能")
            return next({"name": s["name"], "instructions": s["instructions"], "revision": s["revision"]}
                        for s in skills if s["name"] == arguments["name"])
        if name not in profile.get("tool_ids", []):
            raise DomainError("Agent无权使用该工具")
        if name == "knowledge_search":
            if arguments["scope"] not in profile["scopes"]:
                raise DomainError("检索范围未授权")
            return await anyio.to_thread.run_sync(self.search.query, arguments["query"], arguments["scope"], profile["mode"])
        if name in {"knowledge_get", "planning_get"}:
            scope, kind = ("personal", "knowledge") if name == "knowledge_get" else ("planning", "plan")
            if scope not in profile["scopes"]:
                raise DomainError("读取范围未授权")
            row = self.store.get(arguments["id"])
            if row["kind"] != kind:
                raise RecordMissing("条目不存在或不属于授权类型")
            return row
        if name == "knowledge_draft":
            return {"status": "draft_only", "data": validate_knowledge(arguments), "saved": False}
        raise DomainError("工具不存在")
