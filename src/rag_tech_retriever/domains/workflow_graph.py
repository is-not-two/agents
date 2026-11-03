"""通用 DAG 工作流契约与模板解析；纯规则，不触碰数据库或模型。"""
from __future__ import annotations

import re
from copy import deepcopy

from rag_tech_retriever.domains.life_planning import DomainError, text

NODE_TYPES = {"input", "retrieve", "tool", "agent", "merge", "approval"}
IDENT = re.compile(r"[a-z][a-z0-9_-]{0,40}\Z")
PLACEHOLDER = re.compile(r"\{\{([^{}]{1,80})\}\}")
RETRY_ON = {"timeout", "tool_error"}
ON_ERROR = {"fail", "continue", "fallback"}
JOIN_POLICY = {"all_success", "any_success"}


def _integer(value: object, label: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise DomainError(f"{label}必须是 {low}–{high} 的整数")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise DomainError(f"{label}只允许小写字母、数字、_ 或 -，最多 41 字符")
    return value


def _retry(raw: object, node_id: str) -> dict | None:
    """Normalize an optional per-node retry policy; total attempts includes the first call."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {"max_attempts", "backoff_ms", "retry_on"}:
        raise DomainError(f"节点 {node_id} 重试配置包含无效字段")
    retry_on = raw.get("retry_on", ["timeout", "tool_error"])
    if not isinstance(retry_on, list) or not retry_on or any(item not in RETRY_ON for item in retry_on):
        raise DomainError(f"节点 {node_id} 重试类型只支持 timeout/tool_error")
    return {
        "max_attempts": _integer(raw.get("max_attempts", 1), f"节点 {node_id} 最大尝试次数", 1, 4),
        "backoff_ms": _integer(raw.get("backoff_ms", 500), f"节点 {node_id} 重试退避", 100, 5000),
        "retry_on": list(dict.fromkeys(retry_on)),
    }


def _node(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise DomainError("工作流节点必须为对象")
    node_id = _identifier(raw.get("id"), "节点 ID")
    kind = raw.get("type")
    if not isinstance(kind, str) or kind not in NODE_TYPES:
        raise DomainError("工作流节点类型不支持")
    execution = kind in {"retrieve", "tool", "agent", "merge"}
    allowed = {"id", "type"}
    if execution:
        allowed |= {"retry", "timeout_s", "on_error", "fallback"}
    if kind == "retrieve":
        allowed |= {"agent_id", "query", "limit"}
    elif kind == "tool":
        allowed |= {"agent_id", "tool_id", "arguments"}
    elif kind == "agent":
        allowed |= {"agent_id", "query"}
    elif kind == "merge":
        allowed |= {"strategy"}
    elif kind == "approval":
        allowed |= {"message"}
    if set(raw) - allowed:
        raise DomainError(f"节点 {node_id} 包含无效字段")
    node = {"id": node_id, "type": kind}
    if kind in {"retrieve", "tool", "agent"}:
        agent_id = raw.get("agent_id", "")
        if agent_id:
            node["agent_id"] = text(agent_id, f"节点 {node_id} Agent ID", 100, True)
    if kind == "retrieve":
        node["query"] = text(raw.get("query", ""), f"节点 {node_id} 查询", 2000)
        node["limit"] = _integer(raw.get("limit", 5), "引用数量", 1, 10)
    elif kind == "tool":
        node["tool_id"] = text(raw.get("tool_id", ""), f"节点 {node_id} 工具", 64, True)
        arguments = raw.get("arguments", {})
        if not isinstance(arguments, dict) or len(json_size(arguments)) > 16000:
            raise DomainError(f"节点 {node_id} 工具参数必须为大小受限的对象")
        node["arguments"] = deepcopy(arguments)
    elif kind == "agent":
        node["query"] = text(raw.get("query", ""), f"节点 {node_id} 指令", 4000, True)
    elif kind == "merge":
        strategy = raw.get("strategy", "concat")
        if strategy != "concat":
            raise DomainError("合并节点目前只支持 concat")
        node["strategy"] = strategy
    elif kind == "approval":
        node["message"] = text(raw.get("message", ""), f"节点 {node_id} 确认说明", 1000, True)
    if execution:
        retry = _retry(raw.get("retry"), node_id)
        if retry:
            node["retry"] = retry
        if raw.get("timeout_s") is not None:
            node["timeout_s"] = _integer(raw.get("timeout_s"), f"节点 {node_id} 超时", 5, 300)
        on_error = raw.get("on_error", "fail")
        if on_error not in ON_ERROR:
            raise DomainError(f"节点 {node_id} 失败策略只支持 fail/continue/fallback")
        node["on_error"] = on_error
        fallback = raw.get("fallback")
        if on_error == "fallback":
            if not isinstance(fallback, dict) or not fallback or len(json_size(fallback)) > 16000:
                raise DomainError(f"节点 {node_id} fallback 必须为非空且大小受限的对象")
            node["fallback"] = deepcopy(fallback)
        elif fallback is not None:
            raise DomainError(f"节点 {node_id} 只有 fallback 策略可配置 fallback 结果")
    return node


def json_size(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def resolve(value: object, context: dict, label: str = "模板") -> object:
    """Resolve only {{input.x}} and {{nodes.id.output}} paths; unknown paths fail closed."""
    if isinstance(value, str):
        matches = PLACEHOLDER.findall(value)
        if not matches:
            return value
        if len(matches) == 1 and value == "{{" + matches[0] + "}}":
            return _path(matches[0], context, label)
        result = value
        for path in matches:
            replacement = _path(path, context, label)
            if not isinstance(replacement, (str, int, float)):
                raise DomainError(f"{label}只能嵌入文本或数字")
            result = result.replace("{{" + path + "}}", str(replacement))
        return result
    if isinstance(value, dict):
        return {key: resolve(item, context, label) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, context, label) for item in value]
    return value


def _path(path: str, context: dict, label: str) -> object:
    parts = path.split(".")
    if parts[0] == "input" and len(parts) == 2:
        if parts[1] not in context.get("input", {}):
            raise DomainError(f"{label}引用了不存在的输入：{path}")
        return context["input"][parts[1]]
    if parts[0] == "nodes" and len(parts) == 3:
        node = context.get("nodes", {}).get(parts[1])
        if node is None or parts[2] not in node:
            raise DomainError(f"{label}引用了不存在的节点输出：{path}")
        return node[parts[2]]
    raise DomainError(f"{label}只允许 input.* 或 nodes.<id>.* 路径")


def validate_graph_workflow(payload: dict) -> dict:
    """Reject cycles, duplicates, unreachable nodes and ambiguous terminals."""
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 30:
        raise DomainError("工作流节点必须为 2–30 个")
    clean = [_node(raw) for raw in nodes]
    ids = [node["id"] for node in clean]
    if len(set(ids)) != len(ids):
        raise DomainError("工作流节点 ID 不能重复")
    if sum(node["type"] == "input" for node in clean) != 1:
        raise DomainError("工作流必须且只能有一个 input 节点")
    edges = payload.get("edges")
    if not isinstance(edges, list) or not 1 <= len(edges) <= 100:
        raise DomainError("工作流至少需要一条边，最多 100 条")
    clean_edges: list[list[str]] = []
    for edge in edges:
        if (not isinstance(edge, list) or len(edge) != 2
                or not all(isinstance(item, str) and item in ids for item in edge)
                or edge[0] == edge[1]):
            raise DomainError("工作流边必须引用两个不同节点")
        pair = [edge[0], edge[1]]
        if pair not in clean_edges:
            clean_edges.append(pair)
    incoming = {node_id: 0 for node_id in ids}
    outgoing = {node_id: [] for node_id in ids}
    for source, target in clean_edges:
        incoming[target] += 1
        outgoing[source].append(target)
    input_id = next(node["id"] for node in clean if node["type"] == "input")
    if incoming[input_id]:
        raise DomainError("input 节点不能有入边")
    # Kahn topological sort detects cycles without recursion.
    degree = dict(incoming)
    ready = [node_id for node_id, value in degree.items() if value == 0]
    visited = []
    while ready:
        node_id = ready.pop(0)
        visited.append(node_id)
        for target in outgoing[node_id]:
            degree[target] -= 1
            if degree[target] == 0:
                ready.append(target)
    if len(visited) != len(ids) or visited[0] != input_id:
        raise DomainError("工作流必须从 input 开始且不能有环")
    reachable = {input_id}
    stack = [input_id]
    while stack:
        for target in outgoing[stack.pop()]:
            if target not in reachable:
                reachable.add(target)
                stack.append(target)
    if reachable != set(ids):
        raise DomainError("工作流存在从 input 不可达的节点")
    terminals = [node_id for node_id in ids if not outgoing[node_id]]
    if not terminals:
        raise DomainError("工作流缺少终止节点")
    default_agent = text(payload.get("agent_id", ""), "默认 Agent ID", 100)
    if default_agent and default_agent not in {node.get("agent_id") for node in clean if node.get("agent_id")}:
        # It is a fallback, not a reference requirement; the service resolves it.
        pass
    join_policy = payload.get("join_policy", "all_success")
    if join_policy not in JOIN_POLICY:
        raise DomainError("汇合策略只支持 all_success/any_success")
    return {
        "title": text(payload.get("title", ""), "流程名称", 160, True),
        "kind": "graph",
        "agent_id": default_agent,
        "nodes": clean,
        "edges": clean_edges,
        "max_parallel": _integer(payload.get("max_parallel", 1), "并行度", 1, 4),
        "max_retries": _integer(payload.get("max_retries", 1), "节点重试", 0, 3),
        "node_timeout_seconds": _integer(payload.get("node_timeout_seconds", 60), "节点超时", 5, 300),
        "join_policy": join_policy,
    }
