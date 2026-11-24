"""Private AI draft projects; execution never receives tools or file access."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.platform.draft_projects import KIND, DraftProjects


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, max_length=2000)


class ActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=1)
    action: Literal["advance", "pause", "resume", "gate", "approve", "revise", "choices"]
    node: str = Field(default="", max_length=24)
    value: str = Field(default="", max_length=1000)


def create_router(context: WorkspaceContext) -> APIRouter:
    """Use the shared authenticated application and versioned private record store."""
    router = APIRouter(prefix="/api/draft-projects")
    service = DraftProjects(context.store, context.search.connection)

    @router.get("")
    def listing() -> list:
        return context.store.list("agent_session", limit=30, data_kinds=(KIND,), omit=("history", "stages"))

    @router.post("", status_code=201)
    def create(payload: ProjectInput) -> dict:
        return service.create(payload.goal)

    @router.get("/{record_id}")
    def detail(record_id: str) -> dict:
        return service.get(record_id)

    @router.post("/{record_id}/action")
    def action(record_id: str, payload: ActionInput) -> dict:
        if payload.action == "advance":
            return service.advance(record_id, payload.version)
        if payload.action == "choices":
            return {"options": service.choices(record_id, payload.version, payload.node, payload.value)}
        return service.change(record_id, payload.version, payload.action, payload.node, payload.value)

    return router
