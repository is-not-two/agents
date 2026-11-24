"""AI 优化简历：模板列表、生成草稿、人工确认后另存留痕。"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordOut
from rag_tech_retriever.platform.resume_optimizer import ResumeOptimizer
from rag_tech_retriever.platform.resume_service import ResumeService


class DraftInput(BaseModel):
    template_id: str = Field(min_length=1, max_length=64)
    resume_id: str = Field(min_length=1, max_length=100)
    lead_id: str = Field(min_length=1, max_length=100)


class ApplyInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    draft: str = Field(min_length=1, max_length=50000)
    confirmation: str


def create_router(context: WorkspaceContext) -> APIRouter:
    """草稿不写库；确认后另存为知识记录，不覆盖简历本体。"""
    router = APIRouter()
    resumes = ResumeService(context.store, context.journal.root, context.config)
    optimizer = ResumeOptimizer(
        context.store, resumes, getattr(context.search, "connection", None)
    )

    @router.get("/api/resume/templates")
    def templates() -> list:
        return optimizer.templates()

    @router.post("/api/resume/optimize")
    def optimize(payload: DraftInput) -> dict:
        return optimizer.draft(payload.template_id, payload.resume_id, payload.lead_id)

    @router.post("/api/resume/apply", status_code=201, response_model=RecordOut)
    def apply(payload: ApplyInput) -> dict:
        return optimizer.apply(payload.title, payload.draft, payload.confirmation)

    return router
