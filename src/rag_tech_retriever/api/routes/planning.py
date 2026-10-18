"""planning 路由：输入/领域校验与服务调用。"""

from copy import deepcopy
from uuid import uuid4

from fastapi import APIRouter

from rag_tech_retriever.api.dependencies import WorkspaceContext, visible
from rag_tech_retriever.api.models import RecordInput
from rag_tech_retriever.domains.life_planning import DomainError, inspect_branch, validate_plan
from rag_tech_retriever.platform.record_store import RecordMissing


def create_router(context: WorkspaceContext) -> APIRouter:
    """用服务容器创建本模块路由。"""
    router = APIRouter()
    store = context.store

    @router.get("/api/plans")
    def plans_list(trash: bool = False) -> list:
        return [visible(row) for row in store.list("plan", deleted=trash)]

    @router.post("/api/plans", status_code=201)
    def plan_create(payload: RecordInput) -> dict:
        return visible(store.save("plan", validate_plan(payload.data)))

    @router.put("/api/plans/{record_id}")
    def plan_update(record_id: str, payload: RecordInput) -> dict:
        return visible(store.save("plan", validate_plan(payload.data), record_id, payload.version))

    def tree_plan(record_id: str) -> dict:
        row = store.get(record_id)
        if row["kind"] != "plan":
            raise RecordMissing("规划不存在")
        return deepcopy(row["data"])

    @router.post("/api/plans/{record_id}/nodes", status_code=201)
    def node_create(record_id: str, payload: RecordInput) -> dict:
        """在指定父节点旁新增子节点，首次添加自动建立兼容存储容器。"""
        data = tree_plan(record_id)
        parent_id = payload.data.get("parent_id", "")
        if parent_id:
            act = next(
                (a for a in data["acts"] if any(n["id"] == parent_id for n in a["nodes"])), None
            )
            if act is None:
                raise DomainError("父节点不存在，请刷新后重试")
        else:
            if not data["acts"]:
                data["acts"].append({"id": uuid4().hex, "title": "任务树", "nodes": []})
            act = data["acts"][0]
        act["nodes"].append({**payload.data, "id": uuid4().hex})
        return visible(store.save("plan", validate_plan(data), record_id, payload.version))

    @router.put("/api/plans/{record_id}/nodes/{node_id}")
    def node_update(record_id: str, node_id: str, payload: RecordInput) -> dict:
        """更新节点及所属父节点；组织层级和前置条件分别校验。"""
        data = tree_plan(record_id)
        target = next((n for a in data["acts"] for n in a["nodes"] if n["id"] == node_id), None)
        if target is None:
            raise RecordMissing("节点不存在")
        target.update({**payload.data, "id": node_id})
        return visible(store.save("plan", validate_plan(data), record_id, payload.version))

    @router.get("/api/plans/{record_id}/nodes/{node_id}/delete-preview")
    def node_delete_preview(record_id: str, node_id: str) -> dict:
        """返回同一记录版本的删除范围与阻断任务；只读预检不构成删除授权。"""
        row = store.get(record_id)
        if row["kind"] != "plan":
            raise RecordMissing("规划不存在")
        data = row["data"]
        if not any(n["id"] == node_id for a in data["acts"] for n in a["nodes"]):
            raise RecordMissing("节点不存在")
        return {"version": row["version"], **inspect_branch(data, node_id)}

    @router.delete("/api/plans/{record_id}/nodes/{node_id}")
    def node_delete(record_id: str, node_id: str, version: int, cascade: bool = False) -> dict:
        """显式确认后删除整棵子树；外部前置引用仍拒绝悬空。"""
        data = tree_plan(record_id)
        nodes = [n for a in data["acts"] for n in a["nodes"]]
        if not any(n["id"] == node_id for n in nodes):
            raise RecordMissing("节点不存在")
        preview = inspect_branch(data, node_id)
        removed = {node["id"] for node in preview["affected"]}
        if len(removed) > 1 and not cascade:
            raise DomainError("节点包含子节点，请明确确认删除整条分支")
        if not preview["can_delete"]:
            raise DomainError("其他节点仍依赖这条分支，请先调整前置条件")
        for act in data["acts"]:
            act["nodes"] = [n for n in act["nodes"] if n["id"] not in removed]
        return visible(store.save("plan", validate_plan(data), record_id, version))

    return router
