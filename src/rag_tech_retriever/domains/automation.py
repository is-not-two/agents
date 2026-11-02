"""Agent、固定流程和运行记录契约；只校验内容，不依赖数据库或 UI。"""

import math
import re
from copy import deepcopy

from rag_tech_retriever.domains.life_planning import DomainError, text


def integer(value: object, label: str, low: int, high: int) -> int:
    """拒绝布尔值和越界参数。"""
    if type(value) is not int or not low <= value <= high:
        raise DomainError(f"{label}必须是 {low}–{high} 的整数")
    return value


def validate_agent(payload: dict) -> dict:
    """保存角色提示词及可用检索范围，密钥与模型连接不属于角色配置。"""
    scopes = payload.get("scopes", ["personal", "docs", "planning"])
    if not isinstance(scopes, list) or not scopes or any(
        not isinstance(scope, str) or scope not in {"personal", "docs", "planning"}
        for scope in scopes
    ):
        raise DomainError("至少选择一个有效检索范围")
    mode = payload.get("mode", "text")
    if not isinstance(mode, str) or mode not in {"text", "vector"}:
        raise DomainError("检索模式只支持全文或技术文档向量")
    generate = payload.get("generate", False)
    if not isinstance(generate, bool):
        raise DomainError("生成开关必须为布尔值")
    bindings = {}
    for field in ("skill_ids", "tool_ids", "mcp_server_ids"):
        values = payload.get(field, [])
        if (not isinstance(values, list) or len(values) > 32 or any(
            not isinstance(item, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", item) for item in values
        )):
            raise DomainError("Agent技能/工具/服务绑定必须为最多32个有效标识")
        bindings[field] = list(dict.fromkeys(values))
    sections = {}
    for name, allowed in {"model": {"alias", "temperature", "max_tokens"},
                          "budget": {"max_rounds", "max_tool_calls", "max_context_chars"},
                          "context": {"strategy", "max_messages", "keep_recent_users"}, "memory": {"scope"},
                          "handoffs": {"allowed"}}.items():
        value = payload.get(name, {})
        if not isinstance(value, dict) or set(value) - allowed:
            raise DomainError(f"Agent {name} 配置包含无效字段")
        sections[name] = value
    model, budget, context = sections["model"], sections["budget"], sections["context"]
    scope = sections["memory"].get("scope", "none")
    allowed = sections["handoffs"].get("allowed", [])
    if (not isinstance(allowed, list) or len(allowed) > 32 or any(
            not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", item) for item in allowed)):
        raise DomainError("交接白名单须为最多32个有效Agent标识")
    if not isinstance(scope, str) or scope not in {"none", "session", "persistent"}:
        raise DomainError("记忆范围只支持 none/session/persistent")
    alias = model.get("alias", "")
    if not isinstance(alias, str) or (alias and not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", alias)):
        raise DomainError("模型别名必须为管理员登记的标识")
    temperature = model.get("temperature")
    if temperature is not None and (type(temperature) not in {int, float}
                                   or not 0 <= temperature <= 2 or not math.isfinite(temperature)):
        raise DomainError("temperature 必须为 0–2 的有限数值")
    tokens = model.get("max_tokens")
    if tokens is not None:
        integer(tokens, "输出Token上限", 1, 1000000)
    normalized_budget = {}
    for key in ("max_rounds", "max_tool_calls", "max_context_chars"):
        value = budget.get(key)
        normalized_budget[key] = None if value is None else integer(value, key, 1, 1000000)
    if not isinstance(context.get("strategy", "window"), str) or context.get("strategy", "window") not in {"window", "verbatim_window"}:
        raise DomainError("只支持可审计窗口或逐字折叠，不接受未经验证的有损摘要策略")
    return {
        **bindings,
        "title": text(payload.get("title", ""), "Agent 名称", 160, True),
        "system_prompt": text(payload.get("system_prompt", ""), "角色指令", 10000),
        "scopes": list(dict.fromkeys(scopes)),
        "mode": mode,
        "result_limit": integer(payload.get("result_limit", 5), "引用数量", 1, 10),
        "generate": generate,
        "memory": {"scope": scope},
        "handoffs": {"allowed": list(dict.fromkeys(allowed))},
        "model": {"alias": alias, "temperature": temperature, "max_tokens": tokens},
        "budget": normalized_budget,
        "context": {"strategy": context.get("strategy", "window"), "max_messages": integer(
            context.get("max_messages", 20), "上下文消息上限", 2, 1000),
            "keep_recent_users": integer(context.get("keep_recent_users", 2), "保留原样用户消息数", 1, 20)},
    }


def validate_workflow(payload: dict) -> dict:
    """两个已实现的流程类型，配置版本与执行版本分离。"""
    kind = payload.get("kind", "answer")
    if not isinstance(kind, str) or kind not in {"answer", "ingest"}:
        raise DomainError("流程只支持检索回答或知识入库")
    return {
        "title": text(payload.get("title", ""), "流程名称", 160, True),
        "kind": kind,
        "agent_id": text(payload.get("agent_id", ""), "Agent ID", 100, kind == "answer"),
        "chunk_size": integer(payload.get("chunk_size", 1500), "片段字数", 200, 6000),
    }


def validate_run(payload: dict) -> dict:
    """恢复已存运行记录时验证必要结构，禁止伪造类型进入其他领域。"""
    if not isinstance(payload.get("kind"), str) or not isinstance(payload.get("status"), str):
        raise DomainError("运行类型与状态必须是文本")
    if payload.get("kind") not in {"answer", "ingest", "agent"} or payload.get("status") not in {
        "running", "completed", "fallback", "awaiting_confirmation", "confirmed", "failed"
    }:
        raise DomainError("运行记录类型或状态错误")
    text(payload.get("title", ""), "运行名称", 160, True)
    text(payload.get("workflow_id", ""), "流程 ID", 100, True)
    if not isinstance(payload.get("steps"), list) or not isinstance(payload.get("input"), dict):
        raise DomainError("运行步骤或输入格式错误")
    if not isinstance(payload.get("result", {}), dict):
        raise DomainError("运行结果格式错误")
    if payload["kind"] == "agent":
        frozen = payload.get("agent")
        if (not isinstance(frozen, dict) or frozen.get("kind") != "agent_profile"
                or not isinstance(frozen.get("id"), str) or not isinstance(frozen.get("data"), dict)):
            raise DomainError("Agent运行缺少有效的配置快照")
        integer(frozen.get("version"), "Agent版本", 1, 2147483647)
        # This validator is used by public workflow_run backup imports. Private
        # agent_session records have a separate lifecycle and cannot be imported.
        if validate_agent(frozen["data"])["memory"]["scope"] != "none":
            raise DomainError("会话及长期记忆运行不能进入公共工作区恢复")
        for field in ("messages", "skills", "pending_calls", "call_ids"):
            if not isinstance(payload.get(field, []), list):
                raise DomainError("Agent运行状态字段格式错误")
        for field in ("calls_used", "model_steps"):
            integer(payload.get(field, 0), "Agent运行计数", 0, 1000000)
        if not isinstance(payload.get("tool_specs", {}), dict):
            raise DomainError("Agent工具配置格式错误")
        trace = payload.get("trace", [])
        if not isinstance(trace, list) or len(trace) > 10000:
            raise DomainError("Agent追踪必须为有界列表")
        for event in trace:
            if not isinstance(event, dict) or event.get("type") not in {"context", "model"}:
                raise DomainError("Agent追踪事件格式错误")
            if event["type"] == "model":
                integer(event.get("duration_ms"), "模型耗时", 0, 86400000)
                usage = event.get("usage")
                if not isinstance(usage, dict):
                    raise DomainError("模型用量格式错误")
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    if usage.get(key) is not None:
                        integer(usage[key], "模型用量", 0, 2147483647)
        if payload["status"] == "awaiting_confirmation" and not payload.get("pending_calls"):
            raise DomainError("待确认Agent运行必须包含工具调用")
    for step in payload["steps"]:
        if not isinstance(step, dict) or not isinstance(step.get("status"), str) or step.get("status") not in {
            "completed", "skipped", "fallback", "failed"
        }:
            raise DomainError("运行步骤格式错误")
        text(step.get("title", ""), "步骤名称", 160, True)
        text(step.get("detail", ""), "步骤说明", 10000)
        integer(step.get("duration_ms", 0), "步骤耗时", 0, 86400000)
    result = payload.get("result", {})
    if payload["kind"] == "ingest":
        from rag_tech_retriever.domains.knowledge import validate_knowledge

        chunks = payload.get("result", {}).get("chunks", [])
        if not isinstance(chunks, list) or len(chunks) > 500:
            raise DomainError("入库片段格式错误")
        for chunk in chunks:
            validate_knowledge(chunk)
        if payload["status"] in {"awaiting_confirmation", "confirmed"} and not chunks:
            raise DomainError("待确认入库记录必须包含片段")
        if payload["status"] == "confirmed":
            created = result.get("created_ids")
            if not isinstance(created, list) or not created or any(
                not isinstance(value, str) or not value for value in created
            ):
                raise DomainError("已入库记录缺少知识 ID")
    else:
        if (payload["kind"] == "answer" and isinstance(payload.get("agent"), dict)
                and validate_agent(payload["agent"].get("data", {}))["memory"]["scope"] != "none"):
            raise DomainError("含会话或长期记忆的回答不能进入公共工作区恢复")
        if not isinstance(result.get("hits", []), list) or not isinstance(result.get("notes", []), list):
            raise DomainError("运行引用或提示格式错误")
        text(result.get("answer", ""), "运行回答", 100000)
        for hit in result.get("hits", []):
            if not isinstance(hit, dict):
                raise DomainError("引用格式错误")
            text(hit.get("title", ""), "引用标题", 10000)
            text(hit.get("content", ""), "引用正文", 100000)
    return deepcopy(payload)


VALIDATORS = {
    "agent_profile": validate_agent, "workflow": validate_workflow, "workflow_run": validate_run
}
