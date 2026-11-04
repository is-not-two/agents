"""history 路由：输入/领域校验与服务调用。"""

from fastapi import APIRouter

from rag_tech_retriever.api.dependencies import WorkspaceContext, visible
from rag_tech_retriever.api.models import RestoreInput
from rag_tech_retriever.domains.jobs import VALIDATORS as JOB_KINDS
from rag_tech_retriever.platform.jobs import JobsService
from rag_tech_retriever.platform.record_store import VersionConflict

#: 侧栏回收站汇总的公开工作区类型；私密/审计 kinds 不走这里。
TRASH_KINDS: tuple[str, ...] = (
    "knowledge", "bookmark", "plan", "lesson", "learning_card", *sorted(JOB_KINDS),
)
#: 回收站只需要标题与短摘要，不把正文/图结构整包传给浏览器。
TRASH_OMIT = (
    "content", "acts", "nodes", "edges", "graph", "graph_json",
    "storylines", "resume_text", "weak_points", "questions", "notes",
)
_TRASH_LABELS = {
    "knowledge": "知识", "bookmark": "收藏", "plan": "规划",
    "lesson": "谨记", "learning_card": "复习卡",
    "job_lead": "岗位", "application": "投递", "interview_report": "面试复盘",
    "resume_version": "简历版本", "company_capability": "公司能力",
}


def _trash_title(kind: str, data: dict) -> str:
    """回收站条目标题：优先用业务标题，求职类拼公司与岗位。"""
    company = str(data.get("company") or "").strip()
    role = str(data.get("title") or data.get("role") or "").strip()
    if kind in {"job_lead", "application", "interview_report"} and company and role:
        return f"{company} / {role}"
    for key in ("title", "name", "company", "question"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return _TRASH_LABELS.get(kind, kind)


def _trash_subtitle(kind: str, data: dict) -> str:
    """一句话补充；截断正文，避免回收站列表把大字段带回前端。"""
    if kind == "knowledge":
        return str(data.get("content") or "").strip()[:80]
    if kind == "bookmark":
        return str(data.get("url") or "").strip()[:120]
    if kind in JOB_KINDS:
        return str(data.get("status") or data.get("role") or "").strip()[:80]
    if kind == "learning_card":
        return str(data.get("due_at") or "复习卡").strip()[:80]
    if kind == "lesson":
        return str(data.get("type") or "谨记").strip()[:80]
    return ""


def create_router(context: WorkspaceContext) -> APIRouter:
    """用服务容器创建本模块路由。"""
    router = APIRouter()
    store = context.store

    @router.get("/api/trash")
    def trash_overview() -> dict:
        """汇总公开工作区的回收站；一次返回计数与最近条目，避免前端逐模块请求。"""
        counts = store.kind_counts(set(TRASH_KINDS))
        items: list[dict] = []
        for kind in TRASH_KINDS:
            for row in store.list(kind, deleted=True, limit=50, omit=TRASH_OMIT):
                data = row.get("data") or {}
                items.append({
                    "id": row["id"],
                    "kind": kind,
                    "version": row["version"],
                    "title": _trash_title(kind, data),
                    "subtitle": _trash_subtitle(kind, data),
                    "updated_at": row.get("updated_at", ""),
                })
        items.sort(key=lambda item: (item["updated_at"], item["id"]), reverse=True)
        total = sum(counts[kind]["trash"] for kind in TRASH_KINDS)
        return {
            "total": total,
            "truncated": len(items) < total,
            "counts": {k: counts[k]["trash"] for k in TRASH_KINDS if counts[k]["trash"]},
            "items": items,
        }

    @router.delete("/api/records/{record_id}")
    def record_delete(record_id: str, version: int) -> dict:
        kind = store.get(record_id)["kind"]
        if kind in {"notification_outbox", "learning_review", "agent_memory", "agent_session"}:
            raise VersionConflict("此类私有运行或审计记录须通过专用入口处理，不能通用删除")
        if kind in JOB_KINDS:
            return JobsService(store).archive(record_id, version)
        return store.delete(record_id, version)

    @router.get("/api/records/{record_id}/history")
    def record_history(record_id: str) -> list:
        store.get(record_id, True)
        return store.history(record_id)

    @router.post("/api/records/{record_id}/restore")
    def record_restore(record_id: str, payload: RestoreInput) -> dict:
        kind = store.get(record_id, True)["kind"]
        if kind in {"notification_outbox", "learning_review", "agent_memory", "agent_session"}:
            raise VersionConflict("此类私有运行或审计记录不能通过通用历史恢复重放")
        if kind in JOB_KINDS:
            return JobsService(store).restore(record_id, payload.target_version, payload.current_version)
        return visible(store.restore(record_id, payload.target_version, payload.current_version))

    return router
