"""OpenAPI 契约快照：生成、规范化与漂移比对。

契约快照保存在仓库 ``docs/openapi.json``，与代码一起提交。CI/本地校验时把
当前应用生成的结构与快照逐操作比对，任何新增、删除或字段变更都必须显式
更新快照，避免接口契约在无人察觉的情况下漂移。

本模块只读应用路由定义，不触发数据库连接或生命周期钩子。
"""

from __future__ import annotations

import json
from typing import Any

from rag_tech_retriever.common.config_loader import PROJECT_ROOT
from rag_tech_retriever.platform.record_store import RecordStore

SNAPSHOT_PATH = PROJECT_ROOT / "docs" / "openapi.json"

# 三条主线的响应契约锚点：路径/方法/状态码 -> 期望 schema 名。
# 这些端点对外承诺结构化的响应模型，快照更新时也不能退化为裸 dict。
MAINLINE_RESPONSES: dict[tuple[str, str, str], str] = {
    ("/api/query", "post", "200"): "QueryOut",
    ("/api/knowledge", "get", "200"): "RecordOut",
    ("/api/knowledge", "post", "201"): "RecordOut",
    ("/api/jobs", "get", "200"): "JobsOverviewOut",
}


def build_schema() -> dict[str, Any]:
    """构建应用并返回 OpenAPI 文档。

    使用独立的记录表前缀并关闭鉴权，仅用于读取路由与模型定义；应用构造阶段
    不会连接数据库，因此本函数可在无 PostgreSQL 的 CI 步骤中运行。
    """
    # 延迟导入避免 api.main 与路由模块在包初始化期形成循环依赖。
    from rag_tech_retriever.api.main import create_app

    app = create_app(store=RecordStore("openapi_contract"), token="")
    return app.openapi()


def canonical(schema: dict[str, Any]) -> str:
    """返回可直接写入磁盘的规范化 JSON 文本，保证跨平台 diff 稳定。"""
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _operations(schema: dict[str, Any]) -> dict[tuple[str, str], Any]:
    """把 paths 展开为 (路径, 方法) -> 操作定义 的映射。"""
    operations: dict[tuple[str, str], Any] = {}
    for path, item in schema.get("paths", {}).items():
        for method, operation in item.items():
            operations[(path, method)] = operation
    return operations


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """比对两份 OpenAPI 文档，返回人类可读的漂移清单（空列表表示一致）。"""
    old_ops = _operations(old)
    new_ops = _operations(new)
    changes: list[str] = []
    for path, method in sorted(old_ops.keys() - new_ops.keys()):
        changes.append(f"删除端点 {method.upper()} {path}")
    for path, method in sorted(new_ops.keys() - old_ops.keys()):
        changes.append(f"新增端点 {method.upper()} {path}")
    for key in sorted(old_ops.keys() & new_ops.keys()):
        path, method = key
        if canonical(old_ops[key]) != canonical(new_ops[key]):
            changes.append(f"变更端点 {method.upper()} {path}")
    return changes


def _schema_name(schema: dict[str, Any]) -> str:
    """提取内联 schema 或数组元素 schema 的组件名。"""
    ref = schema.get("$ref") or schema.get("items", {}).get("$ref", "")
    return ref.rsplit("/", 1)[-1] if ref else ""


def mainline_problems(schema: dict[str, Any]) -> list[str]:
    """检查三条主线是否仍声明了预期的响应模型；返回问题清单。"""
    problems: list[str] = []
    for (path, method, status), expected in MAINLINE_RESPONSES.items():
        operation = schema.get("paths", {}).get(path, {}).get(method, {})
        content = operation.get("responses", {}).get(status, {}).get("content", {})
        actual = _schema_name(content.get("application/json", {}).get("schema", {}))
        if actual != expected:
            problems.append(f"{method.upper()} {path} -> {status} 期望 {expected}，实际 {actual or '无'}")
    return problems
