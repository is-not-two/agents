"""模拟面试：生成问答草稿、保存会话；删除/恢复复用通用 records 接口。

草稿只在确认保存后落库；会话与真实面试复盘 interview_report 严格分开。
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordInput, RecordOut
from rag_tech_retriever.platform.interview_prep_service import InterviewPrepService
from rag_tech_retriever.platform.resume_service import ResumeService


class GenerateInput(BaseModel):
    lead_id: str = Field(min_length=1, max_length=100)
    resume_id: str = Field(min_length=1, max_length=100)
    mode: str = "practice"
    use_model: bool = False


class AnswerItem(BaseModel):
    index: int = Field(ge=0)
    answer: str = Field(default="", max_length=8000)


class AnswersInput(BaseModel):
    version: int = Field(ge=1)
    answers: list[AnswerItem] = Field(min_length=1)


def create_router(context: WorkspaceContext) -> APIRouter:
    router = APIRouter()
    store = context.store
    resumes = ResumeService(store, context.journal.root, context.config)
    service = InterviewPrepService(
        store, resumes, getattr(context.search, "connection", None)
    )

    @router.post("/api/interview-prep/generate")
    def generate(payload: GenerateInput) -> dict:
        return service.generate(
            payload.lead_id, payload.resume_id, payload.mode, payload.use_model
        )

    @router.get("/api/interview-prep", response_model=list[RecordOut])
    def listing(trash: bool = False) -> list:
        return store.list("interview_prep", deleted=trash)

    @router.post("/api/interview-prep", status_code=201, response_model=RecordOut)
    def create(payload: RecordInput) -> dict:
        return service.save(payload.data)

    @router.put("/api/interview-prep/{record_id}", response_model=RecordOut)
    def update(record_id: str, payload: RecordInput) -> dict:
        return service.save(payload.data, record_id, payload.version)

    @router.post("/api/interview-prep/{record_id}/answers", response_model=RecordOut)
    def submit_answers(record_id: str, payload: AnswersInput) -> dict:
        return service.submit_answers(
            record_id, payload.version,
            [item.model_dump() for item in payload.answers],
        )

    return router
