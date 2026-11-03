"""PostgreSQL 工作台：知识、规划、版本恢复、查询与阶段记录。"""

from __future__ import annotations

import mimetypes
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from rag_tech_retriever.agent.capability_runtime import AgentRuntime
from rag_tech_retriever.agent.collaboration import CollaborationService
from rag_tech_retriever.api.auth import SESSION_COOKIE, Authenticator, LoginThrottle, issue_session
from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.request_guard import body_within_limit
from rag_tech_retriever.api.routes import admin as admin_routes
from rag_tech_retriever.api.routes import automation, history, knowledge, planning
from rag_tech_retriever.api.routes import bookmarks as bookmark_routes
from rag_tech_retriever.api.routes import capabilities as capability_routes
from rag_tech_retriever.api.routes import chat as chat_routes
from rag_tech_retriever.api.routes import collaboration as collaboration_routes
from rag_tech_retriever.api.routes import evaluation as evaluation_routes
from rag_tech_retriever.api.routes import exports as export_routes
from rag_tech_retriever.api.routes import job_insights as job_insight_routes
from rag_tech_retriever.api.routes import jobs as job_routes
from rag_tech_retriever.api.routes import learning as learning_routes
from rag_tech_retriever.api.routes import lessons as lesson_routes
from rag_tech_retriever.api.routes import mcp as mcp_routes
from rag_tech_retriever.api.routes import model_connection as connection_routes
from rag_tech_retriever.api.routes import notifications as notification_routes
from rag_tech_retriever.api.routes import operations as operations_routes
from rag_tech_retriever.api.routes import private as private_routes
from rag_tech_retriever.api.routes import search as search_routes
from rag_tech_retriever.api.routes import stages as stage_routes
from rag_tech_retriever.common.account_auth import is_configured, verify_login
from rag_tech_retriever.common.config_loader import PROJECT_ROOT, ConfigLoader
from rag_tech_retriever.common.middleware.exception import (
    AppError,
    ErrorCode,
    error_payload,
)
from rag_tech_retriever.common.middleware.logger import get_logger, log_event
from rag_tech_retriever.common.middleware.rate_limiter import RateLimitMiddleware
from rag_tech_retriever.common.middleware.tracer import (
    TracerMiddleware,
    current_request_id,
    new_request_id,
)
from rag_tech_retriever.common.schema_policy import resolve_schema_mode
from rag_tech_retriever.common.stage_journal import StageJournal
from rag_tech_retriever.platform.agent_capabilities import CapabilityService
from rag_tech_retriever.platform.mcp_client import ToolError
from rag_tech_retriever.platform.mcp_policy import business_enabled, validate_mcp_config
from rag_tech_retriever.platform.model_connection import ModelConnection
from rag_tech_retriever.platform.operations import configuration_report
from rag_tech_retriever.platform.record_store import (
    RecordMissing,
    RecordStore,
    StorageError,
    VersionConflict,
)
from rag_tech_retriever.platform.search_service import SearchService

# WebP 在部分系统的 mimetypes 库里没有登记，静态资源会以 application/octet-stream
# 返回，浏览器可能下载而不是渲染；显式登记，保证图片按 image/webp 提供。
mimetypes.add_type("image/webp", ".webp")


def create_app(
    store: RecordStore | None = None, root: Path = PROJECT_ROOT, token: str | None = None
) -> FastAPI:
    """创建应用；测试可以注入隔离表、目录和令牌。"""
    settings = ConfigLoader.load_default()
    config = ConfigLoader(settings.settings_path.parent / "web.yaml")
    store = store or RecordStore(
        str(config.get("web.table_prefix", "workspace")),
        config=config,
        pool_size=int(config.get("web.db_pool_size", 0)),
        pool_wait_seconds=float(config.get("web.db_pool_wait_seconds", 5)),
    )
    secret = str(settings.env("WORKSPACE_ACCESS_TOKEN", "")) if token is None else token
    mcp_secret = str(settings.env("WORKSPACE_MCP_TOKEN", ""))
    # 账号密码登录（可选）：仅当账号与密码哈希都配置时启用；未配置则登录页回退令牌方式。
    account_user = str(settings.env("WORKSPACE_USER", "") or "")
    account_hash = str(settings.env("WORKSPACE_PASSWORD_HASH", "") or "")
    account_enabled = is_configured(account_user, account_hash)
    if mcp_secret and (len(mcp_secret) < 32 or mcp_secret != mcp_secret.strip() or secrets.compare_digest(mcp_secret, secret)):
        raise RuntimeError("MCP独立令牌须至少32位、无首尾空白且不同于工作台令牌")
    mcp_config = mcp_routes._load_mcp_config()
    validate_mcp_config(mcp_config)
    if business_enabled(mcp_config) and not mcp_secret:
        raise RuntimeError("启用业务MCP查询必须配置独立WORKSPACE_MCP_TOKEN")
    if str(settings.env("WORKSPACE_REQUIRE_AUTH", "false")).lower() == "true" and not secret:
        raise RuntimeError("请设置 WORKSPACE_ACCESS_TOKEN")
    profile = str(settings.env("WORKSPACE_PROFILE", config.get("operations.profile", "local")))
    if profile not in {"local", "production"}:
        raise RuntimeError("WORKSPACE_PROFILE 必须为 local 或 production")
    schema_mode = resolve_schema_mode(profile, str(settings.env("WORKSPACE_SCHEMA_MODE", "")))
    if profile == "production":
        report = configuration_report(settings.settings_path.parent.parent, profile, settings.env)
        if not report["passed"]:
            raise RuntimeError("生产配置预检失败；请运行 release_gate.py 检查脱敏报告")
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
        corpus_root=root if (root / "config/corpora.yaml").exists() else None,
    )

    # 挂载的子应用（MCP）需要其自身 lifespan 初始化会话管理器；
    # FastAPI 挂载不会代跑子应用 lifespan，故在父 lifespan 中手动接力。
    mounted_lifespans: list = []

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            if schema_mode == "verify":
                store.verify_schema(require_runtime_role=profile == "production")
            else:
                store.ensure_schema()
            if not mounted_lifespans:
                yield
                return
            import contextlib

            async with contextlib.AsyncExitStack() as stack:
                for sub_app in mounted_lifespans:
                    await stack.enter_async_context(sub_app.router.lifespan_context(sub_app))
                yield
        finally:
            # 释放连接池；注入的测试 store 没有池，close 为无操作。
            store.close()

    application = FastAPI(title="时列 · 个人工作台", lifespan=lifespan)
    # 中间件：add 顺序越晚越靠外层——限流在内，追踪最外（访问日志覆盖限流响应）。
    # 限流阈值：WEB_RATE_LIMIT_PER_MINUTE 环境变量 > web.yaml；<=0 关闭（回归/压测场景）。
    rate_limit_env = settings.env("WEB_RATE_LIMIT_PER_MINUTE", "")
    rate_limit = (
        int(rate_limit_env)
        if rate_limit_env.strip().lstrip("-").isdigit()
        else int(config.get("web.rate_limit_per_minute", 120))
    )
    application.add_middleware(
        RateLimitMiddleware,
        limit=rate_limit,
        window_seconds=60,
    )
    application.add_middleware(TracerMiddleware)
    # 静态资源与 JSON 响应压缩：app.css 约 177KB，自托管服务器上不压缩会明显拖慢首屏。
    # Starlette 默认跳过 text/event-stream（MCP/SSE 不受影响）。
    application.add_middleware(GZipMiddleware, minimum_size=1024)
    application.state.store = store
    application.state.journal = journal
    application.state.search = search

    auth = Authenticator(secret, mcp_secret)
    login_throttle = LoginThrottle(
        max_failures=int(config.get("web.login_max_failures", 10)),
        window_seconds=float(config.get("web.login_window_seconds", 300)),
    )

    def guard_error(request: Request, detail: str, code: str, status: int) -> JSONResponse:
        """protect 早退响应：统一错误信封并回传请求 ID（与访问日志可关联）。"""
        request_id = rid(request)
        return JSONResponse(
            error_payload(detail, code, request_id),
            status_code=status,
            headers={"X-Request-ID": request_id},
        )

    @application.middleware("http")
    async def protect(request: Request, call_next):
        mcp_bearer = auth.is_mcp_token(request)
        mcp_path = request.url.path == "/mcp" or request.url.path.startswith("/mcp/")
        if mcp_bearer and request.url.path.startswith("/api/"):
            return guard_error(request, "MCP令牌只允许只读协议入口", ErrorCode.UNAUTHORIZED, 401)
        mcp_authorized = False
        if mcp_path and mcp_secret:
            mcp_authorized = mcp_bearer or bool(secret and auth.authenticated(request))
        if (
            request.url.path.startswith(("/api/", "/mcp"))
            and request.url.path != "/api/session"
            and not (mcp_authorized if mcp_path and mcp_secret else auth.authenticated(request))
        ):
            return guard_error(request, "请先登录", ErrorCode.UNAUTHORIZED, 401)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return guard_error(request, "拒绝跨站写入", ErrorCode.FORBIDDEN, 403)
            limit_key = (
                "web.max_import_bytes"
                if request.url.path in {"/api/import", "/api/import/preview", "/api/knowledge/import/markdown",
                                        "/api/jobs/resumes/upload"}
                else "web.max_body_bytes"
            )
            limit = int(config.get(limit_key, 2097152))
            if not await body_within_limit(request, limit):
                # 按块计数：已知或未知长度超限都不把整包读进内存。
                return guard_error(request, "提交内容超过大小限制", ErrorCode.PAYLOAD_TOO_LARGE, 413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.middleware("http")
    async def mcp_path_alias(request: Request, call_next):
        """MCP 客户端通常按挂载点 /mcp 连接；Starlette 对尾斜杠会 307，部分客户端不跟随。

        在路由前把 /mcp 归一化为 /mcp/，使两种写法等价、不产生重定向。
        """
        if request.url.path == "/mcp":
            request.scope["path"] = "/mcp/"
            request.scope["raw_path"] = b"/mcp/"
        return await call_next(request)

    error_log = get_logger("unhandled")
    # Starlette 内置 404/405 的英文默认文案，替换为面向用户的说法（自定义 detail 不受影响）
    default_http_detail = {"Not Found": "接口不存在", "Method Not Allowed": "该接口不支持此方法"}
    http_error_codes = {
        400: ErrorCode.VALIDATION,
        401: ErrorCode.UNAUTHORIZED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        405: ErrorCode.METHOD_NOT_ALLOWED,
        409: ErrorCode.VERSION_CONFLICT,
        413: ErrorCode.PAYLOAD_TOO_LARGE,
        422: ErrorCode.VALIDATION,
        429: ErrorCode.RATE_LIMITED,
        503: ErrorCode.STORAGE,
    }

    def rid(request: Request) -> str:
        """错误信封的 request_id：优先取追踪器挂在 request.state 的值（与访问日志一致）。"""
        return getattr(request.state, "request_id", "") or current_request_id() or new_request_id()

    def error_response(request: Request, payload: dict, status: int, headers: dict | None = None) -> JSONResponse:
        """统一错误信封响应：回传 X-Request-ID，保证信封与日志可关联。"""
        response_headers = {"X-Request-ID": payload["request_id"]}
        if headers:
            response_headers.update(headers)
        return JSONResponse(payload, status_code=status, headers=response_headers)

    @application.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        """业务异常：code 与 HTTP 状态来自异常类本身（DomainError/JournalError 同属此类）。"""
        return error_response(request, exc.payload(rid(request)), exc.http_status)

    @application.exception_handler(StorageError)
    async def storage_error(request: Request, exc: StorageError):
        code, status = (
            (ErrorCode.NOT_FOUND, 404)
            if isinstance(exc, RecordMissing)
            else (ErrorCode.VERSION_CONFLICT, 409)
            if isinstance(exc, VersionConflict)
            else (ErrorCode.STORAGE, 503)
        )
        return error_response(request, error_payload(str(exc), code, rid(request)), status)

    @application.exception_handler(ToolError)
    async def tool_error(request: Request, exc: ToolError):
        return error_response(request, error_payload(str(exc), ErrorCode.TOOL, rid(request)), 503)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # 统一脱敏：只回显字段位置与规则说明，绝不回显提交内容（input/ctx/url 全部剥离）。
        # 替代历史按 URL 前缀特例化脱敏：新端点无需记得登记即不泄漏。
        fields = [
            {
                "loc": [str(part) for part in error.get("loc", ())],
                "msg": str(error.get("msg", "")),
                "type": str(error.get("type", "")),
            }
            for error in exc.errors()
        ]
        payload = error_payload("提交内容不符合要求，请检查输入", ErrorCode.VALIDATION, rid(request))
        payload["fields"] = fields
        return error_response(request, payload, 400)

    # 注册 Starlette 基类：路由层抛出的 405/404（以及 FastAPI HTTPException 子类）
    # 都走统一信封；否则它们由 Starlette 默认处理，返回无 code / 无 request_id 的裸 detail。
    @application.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) and exc.detail else "请求无法完成"
        detail = default_http_detail.get(detail, detail)
        code = http_error_codes.get(exc.status_code, ErrorCode.INTERNAL)
        return error_response(
            request,
            error_payload(detail, code, rid(request)),
            exc.status_code,
            getattr(exc, "headers", None),
        )

    @application.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        request_id = rid(request)
        log_event(
            error_log,
            "unhandled_error",
            request_id=request_id,
            path=request.url.path,
            error=f"{type(exc).__name__}: {exc}",
        )
        return error_response(
            request,
            error_payload("服务器内部错误，请稍后重试", ErrorCode.INTERNAL, request_id),
            500,
        )

    @application.get("/api/session")
    def session_status(request: Request) -> dict:
        return {
            "required": bool(secret),
            "authenticated": auth.authenticated(request),
            "account_login": account_enabled,
        }

    @application.post("/api/session")
    def login(payload: dict, request: Request):
        """登录：账号密码（可记住 30 天）或访问令牌，签发同一 HMAC 会话 cookie。

        账号路径与令牌路径互不回退：账号密码错即 401，避免把枚举压力放到令牌上。
        同一客户端地址连续失败达到上限会短暂进入 429，成功登录立即清零。
        """
        client = request.client.host if request.client else "unknown"
        wait = login_throttle.blocked(client)
        if wait:
            raise HTTPException(
                429, f"登录失败次数过多，请 {wait} 秒后再试",
                headers={"Retry-After": str(wait)},
            )

        def deny(message: str) -> None:
            login_throttle.fail(client)
            raise HTTPException(401, message)

        remember = bool(payload.get("remember"))
        if "username" in payload or "password" in payload:
            if not account_enabled:
                deny("账号登录未配置，请改用访问令牌")
            username, password = payload.get("username", ""), payload.get("password", "")
            if not isinstance(username, str) or not isinstance(password, str):
                deny("账号或密码不正确")
            if not verify_login(username, password, account_user, account_hash):
                deny("账号或密码不正确")
        else:
            supplied = payload.get("token", "")
            if not isinstance(supplied, str) or (
                secret and not secrets.compare_digest(supplied, secret)
            ):
                deny("访问令牌不正确")
        login_throttle.reset(client)
        response = JSONResponse({"authenticated": True})
        if remember:
            lifetime = int(config.get("web.remember_days", 30)) * 86400
        else:
            lifetime = int(config.get("web.session_hours", 12)) * 3600
        response.set_cookie(
            SESSION_COOKIE,
            issue_session(secret, lifetime),
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=lifetime,
        )
        return response

    @application.delete("/api/session")
    def logout():
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(SESSION_COOKIE)
        return response

    @application.get("/api/status")
    def status() -> dict:
        plans_total = store.count("plan")
        nodes = store.plan_stats()
        try:
            llm_configured = search.connection.public(search.connection.load())["configured"]
        except StorageError:
            llm_configured = False
        return {
            "storage": "PostgreSQL",
            "knowledge_count": store.count("knowledge"),
            "plan_count": plans_total,
            "node_count": nodes["node_count"],
            "done_count": nodes["done_count"],
            "lessons_count": store.count("lesson"),
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
    context.capabilities = CapabilityService(root, store, search, settings.env)
    context.runtime = AgentRuntime(store, search.connection, context.capabilities)
    context.collaboration = CollaborationService(root, store, search.connection, context.capabilities)
    application.include_router(operations_routes.create_router(context))
    application.state.context = context
    application.state.agent_runtime = context.runtime
    application.state.collaboration_service = context.collaboration
    for module in (
        collaboration_routes,
        knowledge,
        bookmark_routes,
        planning,
        history,
        search_routes,
        chat_routes,
        admin_routes,
        lesson_routes,
        job_routes,
        job_insight_routes,
        learning_routes,
        notification_routes,
        export_routes,
        stage_routes,
        automation,
        connection_routes,
        private_routes,
        capability_routes,
        mcp_routes,
        evaluation_routes,
    ):
        application.include_router(module.create_router(context))

    # MCP 标准协议端点（Streamable HTTP）；鉴权与 /api/ 一致（protect 已覆盖 /mcp）
    mcp_asgi = mcp_routes.streamable_app(context.search, mcp_config)
    mounted_lifespans.append(mcp_asgi)
    application.mount("/mcp", mcp_asgi)

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
