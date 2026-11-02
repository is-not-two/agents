"""人工确认复习闭环；普通输入不能伪造评分历史和调度。"""
from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordInput
from rag_tech_retriever.platform.learning import LearningService


class CandidateInput(BaseModel):
    """确认指定版本复盘的选中薄弱点。"""
    version: StrictInt = Field(ge=1)
    points: list[str] = Field(min_length=1, max_length=30)
    confirmation: str


class ReviewInput(BaseModel):
    """请求标识在客户端重试时不变。"""
    version: StrictInt = Field(ge=1)
    rating: StrictInt = Field(ge=0, le=3)
    request_id: str = Field(min_length=16, max_length=100)


def create_router(context: WorkspaceContext) -> APIRouter:
    """服务只在请求时读取配置；不引入进程内调度器。"""
    router = APIRouter()

    @router.get("/api/learning/cards")
    def listing(trash: bool = False) -> dict:
        return LearningService(context.store).overview(trash)

    @router.post("/api/learning/cards", status_code=201)
    def create(payload: RecordInput) -> dict:
        return LearningService(context.store).save(payload.data)

    @router.put("/api/learning/cards/{card_id}")
    def update(card_id: str, payload: RecordInput) -> dict:
        return LearningService(context.store).save(payload.data, card_id, payload.version)

    @router.post("/api/learning/from-interview/{report_id}")
    def from_interview(report_id: str, payload: CandidateInput) -> dict:
        return LearningService(context.store).from_interview(report_id, payload.version, payload.points, payload.confirmation)

    @router.post("/api/learning/cards/{card_id}/review")
    def review(card_id: str, payload: ReviewInput) -> dict:
        return LearningService(context.store).review(card_id, payload.version, payload.rating, payload.request_id)

    @router.get("/api/learning/cards/{card_id}/reviews")
    def reviews(card_id: str) -> list:
        return LearningService(context.store).history(card_id)

    return router
