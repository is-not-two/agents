"""岗位证据分析与周报：默认离线，模型外发逐次确认。"""

from functools import lru_cache

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.job_analysis import JobInsights
from rag_tech_retriever.platform.learning import LearningService
from rag_tech_retriever.platform.notifications import NotificationService
from rag_tech_retriever.platform.weekly_report import WeeklyReport


class ProfileInput(BaseModel):
    revision: str
    data: dict


class AnalyzeInput(BaseModel):
    version: StrictInt = Field(ge=1)
    profile_revision: str
    mode: str = "rules"
    confirmation: str = ""
    request_id: str = Field(default="", max_length=100)


class WeeklyInput(BaseModel):
    day: str = ""
    mode: str = "statistics"
    confirmation: str
    request_id: str = Field(default="", max_length=100)


class GapCardsInput(BaseModel):
    version: StrictInt = Field(ge=1)
    profile_revision: str
    names: list[str] = Field(min_length=1, max_length=30)
    confirmation: str


def create_router(context: WorkspaceContext) -> APIRouter:
    """私密文件跟随运行工作区，不复制用户本机简历。"""
    router = APIRouter()
    @lru_cache(maxsize=1)
    def insights() -> JobInsights:
        return JobInsights(context.journal.root, context.store, context.search.connection)

    @lru_cache(maxsize=1)
    def weekly() -> WeeklyReport:
        return WeeklyReport(context.journal.root, context.store, context.search.connection)

    @router.get("/api/jobs/profile")
    def profile() -> dict:
        return insights().profile()

    @router.put("/api/jobs/profile")
    def profile_save(payload: ProfileInput) -> dict:
        return insights().save_profile(payload.data, payload.revision)

    @router.get("/api/jobs/leads/{lead_id}/gap")
    def gap(lead_id: str) -> dict:
        return insights().gap(lead_id)

    @router.post("/api/jobs/leads/{lead_id}/analyze")
    def analyze(lead_id: str, payload: AnalyzeInput) -> dict:
        return insights().analyze(
            lead_id,
            payload.version,
            payload.profile_revision,
            payload.mode,
            payload.confirmation,
            payload.request_id,
        )

    @router.post("/api/jobs/leads/{lead_id}/learning-cards")
    def learning_cards(lead_id: str, payload: GapCardsInput) -> dict:
        return LearningService(context.store).from_jd(
            lead_id,
            payload.version,
            payload.profile_revision,
            payload.names,
            payload.confirmation,
            insights(),
        )

    @router.get("/api/jobs/report/weekly")
    def weekly_view(day: str = "") -> dict:
        return weekly().saved(day)

    @router.post("/api/jobs/report/weekly")
    def weekly_generate(payload: WeeklyInput) -> dict:
        return weekly().generate(payload.day, payload.mode, payload.confirmation, payload.request_id)

    @router.post("/api/jobs/report/weekly/notify")
    def weekly_notify(payload: WeeklyInput) -> dict:
        if payload.confirmation != "加入周报通知队列":
            raise DomainError("请明确确认周报入队，不会立即发送")
        report = weekly().generate(payload.day, "statistics", "生成并保存周报")
        return NotificationService(context.store).enqueue_weekly(report)

    return router
