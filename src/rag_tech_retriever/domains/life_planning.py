"""主线/支线→阶段→节点；完成态持久化、解锁态派生、依赖 DAG 强校验。"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from uuid import uuid4

from rag_tech_retriever.common.middleware.exception import ValidationError


def inspect_branch(plan: dict, node_id: str) -> dict:
    """计算分支及外部依赖；不更改内容，不将父子组织关系视作前置条件。"""
    nodes = [node for act in plan["acts"] for node in act["nodes"]]
    removed = {node_id}
    children: dict[str, list[str]] = {}
    for node in nodes:
        children.setdefault(node.get("parent_id", ""), []).append(node["id"])
    pending = [node_id]
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in removed:
                removed.add(child)
                pending.append(child)
    affected = [{"id": n["id"], "title": n["title"]} for n in nodes if n["id"] in removed]
    blockers = [
        {"id": n["id"], "title": n["title"]}
        for n in nodes
        if n["id"] not in removed and set(n.get("requires", [])) & removed
    ]
    return {"affected": affected, "blockers": blockers, "can_delete": not blockers}


class DomainError(ValidationError, ValueError):
    """可向用户展示的输入规则错误。

    继承 AppError 体系获得稳定错误码（VALIDATION_ERROR/400）；
    保留 ValueError 基类以兼容既有 except ValueError 调用点。
    """


def text(value: object, label: str, limit: int, required: bool = False) -> str:
    """限制文本类型与长度，避免将任意对象静默转为字符串。"""
    if not isinstance(value, str):
        raise DomainError(f"{label}必须是文本")
    value = value.strip()
    if required and not value:
        raise DomainError(f"请填写{label}")
    if len(value) > limit:
        raise DomainError(f"{label}最多 {limit} 字")
    return value


def validate_plan(payload: dict) -> dict:
    """规范规划文档；拒绝重复 ID、非法前置、循环与已完成节点失去前置条件。"""
    if not isinstance(payload, dict):
        raise DomainError("规划必须是对象")
    kind = payload.get("kind", "main")
    if not isinstance(kind, str) or kind not in {"main", "side"}:
        raise DomainError("规划类型只支持主线或支线")
    done = payload.get("done", False)
    if not isinstance(done, bool):
        raise DomainError("完成标志必须为布尔值")
    plan = {
        "title": text(payload.get("title", ""), "规划名称", 160, True),
        "kind": kind,
        "done": done,
        "description": text(payload.get("description", ""), "规划说明", 20000),
        "acts": [],
    }
    acts = payload.get("acts", [])
    if not isinstance(acts, list) or len(acts) > 100:
        raise DomainError("阶段必须是列表且不超过 100 个")
    ids: set[str] = set()
    nodes: dict[str, dict] = {}
    for act in acts:
        if not isinstance(act, dict):
            raise DomainError("阶段格式错误")
        act_id = text(act.get("id", uuid4().hex), "阶段 ID", 100, True)
        if act_id in ids:
            raise DomainError("阶段或节点 ID 重复")
        ids.add(act_id)
        clean_act = {
            "id": act_id,
            "title": text(act.get("title", ""), "阶段名称", 160, True),
            "description": text(act.get("description", ""), "阶段说明", 20000),
            "nodes": [],
        }
        act_nodes = act.get("nodes", [])
        if not isinstance(act_nodes, list):
            raise DomainError("任务节点必须是列表")
        for node in act_nodes:
            if not isinstance(node, dict):
                raise DomainError("节点格式错误")
            node_id = text(node.get("id", uuid4().hex), "节点 ID", 100, True)
            if node_id in ids:
                raise DomainError("阶段或节点 ID 重复")
            ids.add(node_id)
            if len(ids) > 1000:
                raise DomainError("一条规划最多 1000 个阶段及节点")
            done = node.get("done", False)
            if not isinstance(done, bool):
                raise DomainError("完成标志必须为布尔值")
            due = text(node.get("due_date", ""), "目标日期", 10)
            if due:
                try:
                    date.fromisoformat(due)
                except ValueError as exc:
                    raise DomainError("目标日期格式应为 YYYY-MM-DD") from exc
            dependencies = node.get("requires", [])
            priority = node.get("priority", "p2")
            if not isinstance(priority, str) or priority not in {"p0", "p1", "p2", "p3", "p4"}:
                raise DomainError("优先级必须是 P0–P4")
            if not isinstance(dependencies, list) or any(
                not isinstance(v, str) for v in dependencies
            ):
                raise DomainError("前置节点必须是 ID 列表")
            clean = {
                "id": node_id,
                "title": text(node.get("title", ""), "任务名称", 160, True),
                "description": text(node.get("description", ""), "任务说明", 20000),
                "due_date": due,
                "done": done,
                "priority": priority,
                "parent_id": text(node.get("parent_id", ""), "父节点 ID", 100),
                "requires": list(dict.fromkeys(dependencies)),
            }
            branch_kind = node.get("kind", "side")
            if not isinstance(branch_kind, str) or branch_kind not in {"main", "side"}:
                raise DomainError("节点类型只支持主线或支线")
            clean["kind"] = branch_kind
            nodes[node_id] = clean
            clean_act["nodes"].append(clean)
        plan["acts"].append(clean_act)
    for node in nodes.values():
        parent = node["parent_id"]
        if parent and (parent not in nodes or parent == node["id"]):
            raise DomainError("父节点不存在或指向自身")
        if node["kind"] == "main" and (
            (parent and nodes[parent]["kind"] != "main") or kind != "main"
        ):
            raise DomainError("后续主线只能添加在主线后面")
        for dependency in node["requires"]:
            if dependency not in nodes:
                raise DomainError("前置节点不存在或属于其他规划")
            if dependency == node["id"]:
                raise DomainError("任务不能依赖自身")
        if node["done"] and any(not nodes[key]["done"] for key in node["requires"]):
            raise DomainError("请先完成前置任务；撤销前置完成前，请先撤销后续任务")
    # 迭代拓扑排序避免递归深度问题。
    remaining = {key: set(node["requires"]) for key, node in nodes.items()}
    ready = [key for key, requirements in remaining.items() if not requirements]
    visited: set[str] = set()
    while ready:
        current = ready.pop()
        if current in visited:
            continue
        visited.add(current)
        for key, requirements in remaining.items():
            if current in requirements:
                requirements.remove(current)
                if not requirements:
                    ready.append(key)
    if len(visited) != len(nodes):
        raise DomainError("前置任务形成循环，无法解锁")
    for node in nodes.values():
        seen = {node["id"]}
        parent = node["parent_id"]
        while parent:
            if parent in seen:
                raise DomainError("父子节点形成循环，无法展开")
            seen.add(parent)
            parent = nodes[parent]["parent_id"]
    return plan


def derive_plan(plan: dict) -> dict:
    """计算 locked/available/done 与整体进度，派生字段不落库。"""
    result = deepcopy(plan)
    nodes = {node["id"]: node for act in result["acts"] for node in act["nodes"]}
    completed = sum(node["done"] for node in nodes.values())
    for node in nodes.values():
        node["state"] = (
            "done"
            if node["done"]
            else "available"
            if all(nodes[key]["done"] for key in node["requires"])
            else "locked"
        )
    result["progress"] = {
        "done": completed,
        "total": len(nodes),
        "percent": round(completed / len(nodes) * 100) if nodes else 0,
    }
    for act in result["acts"]:
        total = len(act["nodes"])
        done = sum(node["done"] for node in act["nodes"])
        act["progress"] = {"done": done, "total": total}
        act["state"] = (
            "draft"
            if not total
            else "done"
            if done == total
            else "available"
            if any(n["state"] == "available" for n in act["nodes"])
            else "locked"
        )
    return result
