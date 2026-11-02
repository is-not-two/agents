"""Private slider can request a password again after the server restarts."""

from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.api.routes import private
from rag_tech_retriever.platform.record_store import RecordStore


def test_password_required_after_restart(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(private, "_meta_path", lambda _: tmp_path / "vault.json")
    context = SimpleNamespace(config=None, store=SimpleNamespace(list=lambda _: []))

    def client() -> TestClient:
        app = FastAPI()
        app.include_router(private.create_router(context))
        return TestClient(app)

    first = client()
    assert first.post("/api/private/setup", json={"password": "test-only"}).status_code == 201
    assert first.get("/api/private/status").json()["requires_password"] is True
    assert first.post("/api/private/session", json={}).status_code == 401
    assert first.post("/api/private/session", json={"password": "wrong"}).status_code == 401
    assert first.post("/api/private/session", json={"password": "test-only"}).status_code == 200
    assert first.get("/api/private/status").json()["requires_password"] is False
    assert first.post("/api/private/session", json={}).status_code == 200
    restarted = client()
    assert restarted.get("/api/private/status").json()["requires_password"] is True
    assert restarted.post("/api/private/session", json={}).status_code == 401


def test_private_delete_requires_ticket_kind_and_current_version(tmp_path, monkeypatch) -> None:
    """Exercise actual record deletion, including rejected attempts before mutation."""
    monkeypatch.setattr(private, "_meta_path", lambda _: tmp_path / "vault.json")
    store = RecordStore("qa_" + uuid4().hex[:12])
    store.ensure_schema()
    try:
        with TestClient(create_app(store, tmp_path, token="")) as client:
            assert client.post("/api/private/setup", json={"password": "test-only"}).status_code == 201
            ticket = client.post("/api/private/session", json={"password": "test-only"}).json()["ticket"]
            row = client.post("/api/private/wish", json={
                "ticket": ticket, "data": {"title": "隔离愿望"},
            }).json()
            base = f'/api/private/wish/{row["id"]}'
            assert client.delete(base, params={"version": 1}).status_code == 401
            assert client.delete(base, params={"version": 99, "ticket": ticket}).status_code == 409
            assert client.delete(f'/api/private/diary/{row["id"]}', params={
                "version": 1, "ticket": ticket,
            }).status_code == 404
            assert not store.get(row["id"])["deleted"]
            response = client.delete(base, params={"version": 1, "ticket": ticket})
            assert response.status_code == 200
            assert store.get(row["id"], include_deleted=True)["deleted"]
            assert client.get("/api/private/wish", params={"ticket": ticket}).json() == []
    finally:
        with store.transaction() as cursor:
            cursor.execute(f"DROP TABLE {store.versions}")
            cursor.execute(f"DROP TABLE {store.records}")
