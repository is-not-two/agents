"""请求体大小守卫单测（M6）：超限不整包读入，且下游仍能解析正文。"""

from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from rag_tech_retriever.api.request_guard import body_within_limit


def build_app(limit: int) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not await body_within_limit(
            request, limit
        ):
            return JSONResponse({"detail": "提交内容超过大小限制"}, status_code=413)
        return await call_next(request)

    @app.post("/echo")
    async def echo(payload: dict) -> dict:
        text = payload.get("text", "")
        return {"size": len(text)}

    return app


def test_body_within_limit_preserves_downstream_parsing():
    limit = 4096
    body = json.dumps({"text": "x" * 1000}).encode()
    with TestClient(build_app(limit)) as client:
        response = client.post(
            "/echo", content=body, headers={"content-type": "application/json"}
        )
    assert response.status_code == 200
    assert response.json() == {"size": 1000}


def test_declared_content_length_over_limit_is_rejected():
    limit = 1024
    body = json.dumps({"text": "x" * 5000}).encode()
    with TestClient(build_app(limit)) as client:
        response = client.post(
            "/echo", content=body, headers={"content-type": "application/json"}
        )
    assert response.status_code == 413


def test_chunked_body_over_limit_is_rejected_without_content_length():
    limit = 1024
    body = json.dumps({"text": "x" * 5000}).encode()
    with TestClient(build_app(limit)) as client:
        response = client.post(
            "/echo",
            content=iter([body[:512], body[512:1024], body[1024:]]),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413


def test_body_exactly_at_limit_passes():
    body = json.dumps({"text": "x" * 500}).encode()
    with TestClient(build_app(len(body))) as client:
        response = client.post(
            "/echo", content=body, headers={"content-type": "application/json"}
        )
    assert response.status_code == 200
    assert response.json() == {"size": 500}
