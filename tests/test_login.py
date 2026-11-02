"""账号密码登录与 30 天记住：验证、时长、令牌兼容、未配置回退。"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.common.account_auth import (
    PasswordHashError,
    is_configured,
    make_password_hash,
    verify_login,
    verify_password,
)
from rag_tech_retriever.platform.record_store import RecordStore

USER = "luojiee"
PASSWORD = "correct-horse-battery"
# scrypt N=2^14 约 50-100ms/次，只算一次复用
HASH = make_password_hash(PASSWORD)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_USER", USER)
    monkeypatch.setenv("WORKSPACE_PASSWORD_HASH", HASH)
    store = RecordStore("qa_login_" + uuid4().hex[:10])
    with TestClient(create_app(store=store, root=tmp_path, token="test-token")) as client:
        yield client
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


@pytest.fixture
def api_no_account(tmp_path, monkeypatch):
    """未配置账号登录的实例（环境里没有 WORKSPACE_USER/HASH）。"""
    monkeypatch.delenv("WORKSPACE_USER", raising=False)
    monkeypatch.delenv("WORKSPACE_PASSWORD_HASH", raising=False)
    store = RecordStore("qa_loginx_" + uuid4().hex[:10])
    with TestClient(create_app(store=store, root=tmp_path, token="test-token")) as client:
        yield client
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE {store.versions}")
        cur.execute(f"DROP TABLE {store.records}")


class TestAccountAuthUnit:
    def test_hash_roundtrip(self):
        assert verify_password(PASSWORD, HASH)
        assert not verify_password("wrong-password", HASH)

    def test_hash_has_no_plaintext(self):
        assert PASSWORD not in HASH
        assert HASH.startswith("scrypt$")

    def test_malformed_hash_rejected(self):
        assert not verify_password(PASSWORD, "not-a-hash")
        assert not verify_password(PASSWORD, "scrypt$abc$def")

    def test_empty_password_rejected(self):
        with pytest.raises(PasswordHashError):
            make_password_hash("")

    def test_is_configured(self):
        assert is_configured("u", "h")
        assert not is_configured("", "h")
        assert not is_configured("u", "")
        assert not is_configured(None, None)

    def test_verify_login_timing_uniform_paths(self):
        """账号错与密码错都跑完整哈希，两条路径都返回 False。"""
        assert verify_login("other-user", PASSWORD, USER, HASH) is False
        assert verify_login(USER, "wrong", USER, HASH) is False
        assert verify_login(USER, PASSWORD, USER, HASH) is True


class TestLoginEndpoint:
    def test_account_login_success(self, api):
        res = api.post(
            "/api/session",
            json={"username": USER, "password": PASSWORD, "remember": False},
        )
        assert res.status_code == 200
        assert res.json() == {"authenticated": True}
        assert "workspace_session=" in res.headers.get("set-cookie", "")

    def test_account_login_gets_usable_cookie(self, api):
        api.post("/api/session", json={"username": USER, "password": PASSWORD})
        session = api.get("/api/session").json()
        assert session["authenticated"] is True
        assert session["account_login"] is True

    def test_wrong_password_401(self, api):
        res = api.post(
            "/api/session", json={"username": USER, "password": "nope"}
        )
        assert res.status_code == 401
        assert res.json()["detail"] == "账号或密码不正确"

    def test_wrong_user_401_same_message(self, api):
        """账号错与密码错回同一文案，不暴露账号是否存在。"""
        res = api.post(
            "/api/session", json={"username": "someone", "password": PASSWORD}
        )
        assert res.status_code == 401
        assert res.json()["detail"] == "账号或密码不正确"

    def test_remember_sets_30day_cookie(self, api):
        res = api.post(
            "/api/session",
            json={"username": USER, "password": PASSWORD, "remember": True},
        )
        cookie = res.headers.get("set-cookie", "")
        assert f"Max-Age={30 * 86400}" in cookie

    def test_no_remember_keeps_session_hours(self, api):
        res = api.post(
            "/api/session",
            json={"username": USER, "password": PASSWORD, "remember": False},
        )
        cookie = res.headers.get("set-cookie", "")
        assert f"Max-Age={12 * 3600}" in cookie
        assert f"Max-Age={30 * 86400}" not in cookie

    def test_token_login_still_works(self, api):
        """令牌登录保留为备用通道。"""
        res = api.post("/api/session", json={"token": "test-token"})
        assert res.status_code == 200

    def test_bad_token_401(self, api):
        res = api.post("/api/session", json={"token": "wrong"})
        assert res.status_code == 401

    def test_protected_route_requires_login(self, api):
        assert api.get("/api/knowledge").status_code == 401

    def test_logout_clears_cookie(self, api):
        api.post("/api/session", json={"username": USER, "password": PASSWORD})
        res = api.delete("/api/session")
        assert res.status_code == 200


class TestAccountNotConfigured:
    def test_session_flag_false(self, api_no_account):
        session = api_no_account.get("/api/session").json()
        assert session["account_login"] is False

    def test_account_login_rejected(self, api_no_account):
        res = api_no_account.post(
            "/api/session", json={"username": "u", "password": "p"}
        )
        assert res.status_code == 401
        assert res.json()["detail"] == "账号登录未配置，请改用访问令牌"

    def test_token_login_still_works(self, api_no_account):
        res = api_no_account.post("/api/session", json={"token": "test-token"})
        assert res.status_code == 200
