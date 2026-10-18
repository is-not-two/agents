"""stages 路由：输入/领域校验与服务调用。"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import (
    StageFinishInput,
    StageInput,
)
from rag_tech_retriever.api.stage_summary import stage_summary
from rag_tech_retriever.domains.snapshot import validate_snapshot


def create_router(context: WorkspaceContext) -> APIRouter:
    """用服务容器创建本模块路由。"""
    router = APIRouter()
    store, journal = context.store, context.journal

    @router.get("/api/stage-summary")
    def summary() -> dict:
        return stage_summary(journal, journal.root)

    @router.get("/api/stages")
    def stages() -> list:
        return journal.list()

    @router.post("/api/stages", status_code=201)
    def stage_start(payload: StageInput) -> dict:
        return journal.start(payload.title, payload.objective, store.export())

    @router.post("/api/stages/{stage_id}/finish")
    def stage_finish(stage_id: str, payload: StageFinishInput) -> dict:
        if payload.status == "passed" and not payload.verification:
            raise HTTPException(400, "请填写验证证据，或选择待处理")
        return journal.finish(
            stage_id, payload.completed, payload.issues, payload.verification, payload.status
        )

    @router.get("/api/stages/{stage_id}/rollback-check")
    def rollback_check(stage_id: str) -> dict:
        return journal.rollback(stage_id)

    @router.post("/api/stages/{stage_id}/restore-data")
    def stage_restore_data(stage_id: str, payload: dict) -> dict:
        if payload.get("confirmation") != "恢复数据":
            raise HTTPException(400, "请明确确认恢复数据")
        snapshot = validate_snapshot(journal.data_snapshot(stage_id))
        rescue = {}

        def protect(before: dict) -> None:
            rescue.update(journal.start("数据恢复前保护快照", "保留恢复前所有内容", before))

        result = store.restore_snapshot(snapshot, before_restore=protect)
        journal.finish(
            rescue["id"],
            ["恢复阶段 " + stage_id + " 开始时内容"],
            [],
            [f"事务恢复 {result['restored_records']} 条；原历史保留"],
        )
        return {**result, "rescue_stage_id": rescue["id"]}

    @router.get("/api/stages/{stage_id}/diff")
    def stage_diff(stage_id: str):
        journal.get(stage_id)
        path = journal._folder(stage_id) / "changes.patch"
        return PlainTextResponse(
            path.read_text(encoding="utf-8")
            if path.is_file()
            else "此阶段暂无已保存的文本差异。文件路径与摘要见阶段记录。"
        )

    return router
