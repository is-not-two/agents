"""PostgreSQL 工作台：知识、规划、版本恢复、查询与阶段记录。"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.routes import automation, history, knowledge, planning
from rag_tech_retriever.api.routes import exports as export_routes
from rag_tech_retriever.api.routes import model_connection as connection_routes
from rag_tech_retriever.api.routes import search as search_routes
from rag_tech_retriever.api.routes import stages as stage_routes
from rag_tech_retriever.common.config_loader import PROJECT_ROOT, ConfigLoader
from rag_tech_retriever.common.stage_journal import JournalError, StageJournal
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.model_connection import ModelConnection
from rag_tech_retriever.platform.record_store import (
    RecordMissing,
    RecordStore,
    StorageError,
    VersionConflict,
)
from rag_tech_retriever.platform.search_service import SearchService


def create_app(
    store: RecordStore | None = None, root: Path = PROJECT_ROOT, token: str | None = None
) -> FastAPI:
    """创建应用；测试可以注入隔离表、目录和令牌。"""
    settings = ConfigLoader.load_default()
    config = ConfigLoader(settings.settings_path.parent / "web.yaml")
    store = store or RecordStore(str(config.get("web.table_prefix", "workspace")))
    secret = str(settings.env("WORKSPACE_ACCESS_TOKEN", "")) if token is None else token
    if str(settings.env("WORKSPACE_REQUIRE_AUTH", "false")).lower() == "true" and not secret:
        raise RuntimeError("请设置 WORKSPACE_ACCESS_TOKEN")
    journal = StageJournal(root, root / str(config.get("web.stages_dir", "output/stages")))
    exports = root / str(config.get("web.export_dir", "data/local/exports"))
    search = SearchService(
        store,
        int(config.get("web.search_limit", 10)),
        int(config.get("llm.timeout_seconds", 25)),
        int(config.get("llm.max_tokens", 800)),
        ModelConnection(
            root / str(config.get("llm.connection_file", "data/local/llm-connection.json")),
            int(config.get("llm.test_timeout_seconds", 12)),
        ),
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        store.ensure_schema()
        yield

    application = FastAPI(title="时列 · 个人工作台", lifespan=lifespan)
    application.state.store = store
    application.state.journal = journal
    application.state.search = search

    def authenticated(request: Request) -> bool:
        if not secret:
            return True
        bearer = request.headers.get("Authorization", "")
        if bearer.startswith("Bearer ") and secrets.compare_digest(bearer[7:], secret):
            return True
        try:
            payload, signature = request.cookies.get("workspace_session", "").rsplit(".", 1)
            expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
            return int(payload.split(":")[0]) > time.time() and secrets.compare_digest(
                signature, expected
            )
        except (ValueError, IndexError):
            return False

    @application.middleware("http")
    async def protect(request: Request, call_next):
        if (
            request.url.path.startswith("/api/")
            and request.url.path != "/api/session"
            and not authenticated(request)
        ):
            return JSONResponse({"detail": "请先输入工作台访问令牌"}, status_code=401)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "拒绝跨站写入"}, status_code=403)
            limit_key = (
                "web.max_import_bytes"
                if request.url.path in {"/api/import", "/api/import/preview"}
                else "web.max_body_bytes"
            )
            if len(await request.body()) > int(config.get(limit_key, 2097152)):
                return JSONResponse({"detail": "提交内容超过大小限制"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(StorageError)
    async def storage_error(request: Request, exc: StorageError):
        code = (
            404
            if isinstance(exc, RecordMissing)
            else 409
            if isinstance(exc, VersionConflict)
            else 503
        )
        return JSONResponse({"detail": str(exc)}, status_code=code)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # 默认校验响应可能包含原始输入；凭据接口不能回显提交内容。
        if request.url.path.startswith("/api/model-connection"):
            return JSONResponse({"detail": "连接信息格式不正确，请检查填写内容"}, status_code=400)
        return await request_validation_exception_handler(request, exc)

    @application.exception_handler(DomainError)
    @application.exception_handler(JournalError)
    async def input_error(request: Request, exc: Exception):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @application.get("/api/session")
    def session_status(request: Request) -> dict:
        return {"required": bool(secret), "authenticated": authenticated(request)}

    @application.post("/api/session")
    def login(payload: dict, request: Request):
        supplied = payload.get("token", "")
        if not isinstance(supplied, str) or (
            secret and not secrets.compare_digest(supplied, secret)
        ):
            raise HTTPException(401, "访问令牌不正确")
        response = JSONResponse({"authenticated": True})
        lifetime = int(config.get("web.session_hours", 12)) * 3600
        message = f"{int(time.time()) + lifetime}:{secrets.token_hex(16)}"
        signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        response.set_cookie(
            "workspace_session",
            message + "." + signature,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=lifetime,
        )
        return response

    @application.delete("/api/session")
    def logout():
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("workspace_session")
        return response

    @application.get("/api/status")
    def status() -> dict:
        knowledge, plans = store.list("knowledge"), store.list("plan")
        nodes = [n for p in plans for a in p["data"]["acts"] for n in a["nodes"]]
        try:
            llm_configured = search.connection.public(search.connection.load())["configured"]
        except StorageError:
            llm_configured = False
        return {
            "storage": "PostgreSQL",
            "knowledge_count": len(knowledge),
            "plan_count": len(plans),
            "node_count": len(nodes),
            "done_count": sum(n["done"] for n in nodes),
            "stages_count": len(journal.list()),
            "export_directory": str(exports),
            "auth_enabled": bool(secret),
            "llm_configured": llm_configured,
        }

    @application.get("/health")
    def health() -> dict:
        with store.transaction() as cursor:
            cursor.execute("SELECT 1")
        return {"status": "ok", "storage": "PostgreSQL", "pid": os.getpid()}

    context = WorkspaceContext(store, journal, search, exports, settings, config)
    application.state.context = context
    for module in (
        knowledge,
        planning,
        history,
        search_routes,
        export_routes,
        stage_routes,
        automation,
        connection_routes,
    ):
        application.include_router(module.create_router(context))

    static = Path(__file__).parent / "static"
    static.mkdir(exist_ok=True)
    application.mount("/static", StaticFiles(directory=static), name="static")

    @application.get("/")
    def index():
        return FileResponse(static / "shilie" / "index.html")

    @application.get("/legacy")
    def legacy_index():
        return FileResponse(static / "index.html")

    return application


app = create_app()
