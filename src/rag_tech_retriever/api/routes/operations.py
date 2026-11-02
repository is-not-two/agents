"""Liveness/readiness and authenticated, redacted operational diagnostics."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.common.middleware.tracer import current_request_id
from rag_tech_retriever.platform.operations import configuration_report
from rag_tech_retriever.platform.record_store import StorageError


def create_router(context: WorkspaceContext) -> APIRouter:
    """Keep process liveness independent from optional providers and PostgreSQL."""
    router = APIRouter(tags=["operations"])

    def database_ready() -> bool:
        try:
            timeout = context.config.get("operations.readiness_timeout_seconds", 3)
            if not isinstance(timeout, int) or isinstance(timeout, bool):
                return False
            context.store.ping(timeout_seconds=timeout)
            return True
        except (StorageError, OSError, ValueError):
            return False

    @router.get("/health/live")
    def live() -> dict:
        return {"status": "ok"}

    @router.get("/health/ready")
    def ready() -> JSONResponse:
        ok = database_ready()
        return JSONResponse({"status": "ok" if ok else "unavailable",
                             "checks": {"database": "ready" if ok else "unavailable"}},
                            status_code=200 if ok else 503)

    @router.get("/api/admin/diagnostics")
    def diagnostics() -> dict:
        # Configuration location comes from injected settings, not the journal/temp root.
        report = configuration_report(context.settings.settings_path.parent.parent,
                                      env=context.settings.env)
        ok = database_ready()
        report["checks"].append({"id": "database", "status": "pass" if ok else "fail",
                                 "message": "数据库已就绪" if ok else "数据库暂不可用"})
        report["passed"] = report["passed"] and ok
        report["request_id"] = current_request_id()
        return report

    return router
