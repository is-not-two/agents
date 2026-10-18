"""Agent、固定流程和运行记录契约；只校验内容，不依赖数据库或 UI。"""

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
    return {
        "title": text(payload.get("title", ""), "Agent 名称", 160, True),
        "system_prompt": text(payload.get("system_prompt", ""), "角色指令", 10000),
        "scopes": list(dict.fromkeys(scopes)),
        "mode": mode,
        "result_limit": integer(payload.get("result_limit", 5), "引用数量", 1, 10),
        "generate": generate,
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
    if payload.get("kind") not in {"answer", "ingest"} or payload.get("status") not in {
        "running", "completed", "fallback", "awaiting_confirmation", "confirmed", "failed"
    }:
        raise DomainError("运行记录类型或状态错误")
    text(payload.get("title", ""), "运行名称", 160, True)
    text(payload.get("workflow_id", ""), "流程 ID", 100, True)
    if not isinstance(payload.get("steps"), list) or not isinstance(payload.get("input"), dict):
        raise DomainError("运行步骤或输入格式错误")
    if not isinstance(payload.get("result", {}), dict):
        raise DomainError("运行结果格式错误")
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
