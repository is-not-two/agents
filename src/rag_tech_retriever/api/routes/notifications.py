"""通知摘要预览、显式入队与状态处理；默认关闭外发。"""
from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.notifications import NotificationService


class ConfirmationInput(BaseModel):
    """外部动作必须有独立明确确认。"""
    confirmation: str


class ResolutionInput(BaseModel):
    """CAS 与人工核对结果，不盲重放未知通知。"""
    version: StrictInt = Field(ge=1)
    action: str
    confirmation: str


def create_router(context: WorkspaceContext) -> APIRouter:
    """沿用全局会话、CSRF、限流保护，不开放任意收件人与消息接口。"""
    router = APIRouter()

    @router.get("/api/notifications")
    def listing() -> dict:
        return NotificationService(context.store).listing()

    @router.get("/api/notifications/daily-preview")
    def preview() -> dict:
        return NotificationService(context.store).preview()

    @router.post("/api/notifications/daily")
    def enqueue(payload: ConfirmationInput) -> dict:
        if payload.confirmation != "加入通知队列":
            raise DomainError("请明确确认加入通知队列；入队不代表已发送")
        return NotificationService(context.store).enqueue_daily()

    @router.post("/api/notifications/dispatch")
    def dispatch(payload: ConfirmationInput) -> dict:
        if payload.confirmation != "发送通知":
            raise DomainError("请明确确认发送通知")
        return NotificationService(context.store).dispatch()

    @router.post("/api/notifications/{notification_id}/resolve")
    def resolve(notification_id: str, payload: ResolutionInput) -> dict:
        return NotificationService(context.store).resolve(notification_id, payload.version, payload.action, payload.confirmation)

    return router
