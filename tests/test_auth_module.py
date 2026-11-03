"""鉴权模块单测（M8 纯搬运的回归锚点，不依赖数据库）。"""

from __future__ import annotations

import time

from starlette.requests import Request

from rag_tech_retriever.api.auth import (
    SESSION_COOKIE,
    Authenticator,
    issue_session,
    sign_message,
    verify_session,
)


def make_request(headers: dict[str, str] | None = None) -> Request:
    """构造最小 HTTP request，用于鉴权分支测试。"""
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


def test_session_roundtrip():
    secret = "qa-workspace-token"
    cookie = issue_session(secret, 3600)
    assert verify_session(cookie, secret)
    assert "." in cookie


def test_session_rejects_expired_and_tampered():
    secret = "qa-workspace-token"
    expired_message = f"{int(time.time()) - 1}:{'a' * 32}"
    expired = expired_message + "." + sign_message(secret, expired_message)
    assert not verify_session(expired, secret)

    fresh = issue_session(secret, 3600)
    payload, signature = fresh.rsplit(".", 1)
    assert not verify_session(payload + "." + signature[:-1] + "0", secret)
    assert not verify_session("garbage", secret)
    assert not verify_session("", secret)
    assert not verify_session(fresh, "")


def test_authenticator_without_secret_allows_all():
    auth = Authenticator()
    assert not auth.enabled
    assert auth.authenticated(make_request())


def test_authenticator_bearer_and_cookie():
    secret = "qa-workspace-token"
    auth = Authenticator(secret)
    assert auth.authenticated(make_request({"Authorization": f"Bearer {secret}"}))
    assert not auth.authenticated(make_request({"Authorization": "Bearer wrong"}))
    assert not auth.authenticated(make_request({"Authorization": secret}))

    cookie = issue_session(secret, 3600)
    assert auth.authenticated(make_request({"Cookie": f"{SESSION_COOKIE}={cookie}"}))
    assert not auth.authenticated(
        make_request({"Cookie": f"{SESSION_COOKIE}={issue_session('other', 3600)}"})
    )


def test_authenticator_mcp_token_is_separate():
    auth = Authenticator("qa-workspace-token", "mcp-" + "x" * 32)
    assert auth.is_mcp_token(make_request({"Authorization": "Bearer mcp-" + "x" * 32}))
    assert not auth.is_mcp_token(make_request({"Authorization": "Bearer qa-workspace-token"}))
    assert not Authenticator("qa-workspace-token").is_mcp_token(
        make_request({"Authorization": "Bearer qa-workspace-token"})
    )
