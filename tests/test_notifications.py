"""真实本机 SMTP fixture + 独立 PostgreSQL，验证接收/拒绝/丢回执边界。"""
import os
import socket
import socketserver
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.notifications import NotificationService
from rag_tech_retriever.platform.record_store import RecordStore


@contextmanager
def smtp_fixture(mode="accept"):
    received = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 localhost fixture\r\n")
            while True:
                command = self.rfile.readline(100000)
                if not command:
                    return
                if command.upper().startswith((b"EHLO", b"HELO")):
                    self.wfile.write(b"250 localhost\r\n")
                elif command.upper().startswith(b"DATA"):
                    self.wfile.write(b"354 continue\r\n")
                    chunks = []
                    while True:
                        line = self.rfile.readline(100000)
                        if not line or line == b".\r\n":
                            break
                        chunks.append(line)
                    if mode == "reject":
                        self.wfile.write(b"451 temporary refusal\r\n")
                    else:
                        received.append(b"".join(chunks))
                        if mode == "disconnect":
                            return  # SMTP accepted bytes but response was lost.
                        self.wfile.write(b"250 queued\r\n")
                elif command.upper().startswith(b"QUIT"):
                    self.wfile.write(b"221 bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 ok\r\n")

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_address[1], received
        finally:
            server.shutdown()
            thread.join(timeout=3)


@pytest.fixture
def store():
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    value = RecordStore("qa_notify_" + uuid4().hex[:10])
    value.ensure_schema()
    yield value
    with value.transaction() as cur:
        cur.execute(f"DROP TABLE {value.versions}")
        cur.execute(f"DROP TABLE {value.records}")


def service(store, port=1, **extra):
    env = {"NOTIFY_ENABLED": "true", "SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(port), "SMTP_SECURITY": "local-test", "SMTP_FROM": "sender@example.com", "SMTP_TO": "recipient@example.com", **extra}
    return NotificationService(store, env=lambda key, default="": env.get(key, default))


def test_daily_dedupe_and_real_smtp_accept_once_under_two_workers(store):
    with smtp_fixture() as (port, received):
        sender = service(store, port)
        row = sender.enqueue_daily()["notification"]
        assert sender.enqueue_daily()["reused"]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: sender.dispatch(), range(2)))
        assert sum(len(r["processed"]) for r in results) == 1
        assert len(received) == 1 and ("<" + row["id"] + "@shilie.local>").encode() in received[0]
        saved = store.get(row["id"])
        assert saved["data"]["status"] == "sent" and saved["data"]["smtp_accepted"]
        assert saved["data"]["attempts"] == 1
        assert sender.enqueue_daily()["reused"] and not sender.dispatch()["processed"]
        public = str(sender.public()) + str(saved)
        assert "recipient@example.com" not in public and "sender@example.com" not in public


def test_lost_smtp_response_is_unknown_and_not_automatically_replayed(store):
    with smtp_fixture("disconnect") as (port, received):
        sender = service(store, port)
        row = sender.enqueue_daily()["notification"]
        result = sender.dispatch()["processed"][0]
        assert len(received) == 1
        assert result["data"]["status"] == "unknown" and not result["data"]["retryable"]
        assert not sender.dispatch()["processed"] and len(received) == 1
        with pytest.raises(DomainError):
            sender.resolve(row["id"], result["version"], "retry", "")
        sender.resolve(row["id"], result["version"], "received", "已核对通知结果")
        assert store.get(row["id"])["data"]["resolution"].startswith("用户人工核对")


def test_definite_refusal_and_failed_connection_are_not_sent(store):
    with smtp_fixture("reject") as (port, received):
        sender = service(store, port)
        row = sender.enqueue_daily()["notification"]
        result = sender.dispatch()["processed"][0]
        assert not received and result["data"]["status"] == "failed" and result["data"]["retryable"]
        assert not sender.dispatch()["processed"]  # backoff has not elapsed.
        assert "SMTP 明确拒绝" in store.get(row["id"])["data"]["last_error"]


def test_stale_claim_is_recovered_as_unknown_without_send(store):
    sender = service(store)
    now = datetime(2026, 10, 28, 22, tzinfo=timezone.utc)
    sender.clock = lambda: now
    queued = sender.enqueue_daily()["notification"]
    assert queued["data"]["operation_id"] == "daily:2026-10-29"  # configured UTC+08.
    assert sender._claim()["data"]["status"] == "sending"
    now += timedelta(seconds=181)
    assert sender.recover_stale() == 1
    assert store.get(queued["id"])["data"]["status"] == "unknown"
    assert sender._claim() is None


def test_disabled_config_and_plaintext_remote_fail_before_claim(store):
    sender = service(store, NOTIFY_ENABLED="false")
    row = sender.enqueue_daily()["notification"]
    with pytest.raises(DomainError):
        sender.dispatch()
    with pytest.raises(DomainError):
        service(store, SMTP_HOST="example.com").dispatch()
    assert store.get(row["id"])["data"]["status"] == "pending"
    assert store.get(row["id"])["data"]["attempts"] == 0


def test_queue_excluded_from_backup_and_generic_restore_cannot_replay(store, tmp_path):
    with TestClient(create_app(store, tmp_path, token="")) as api:
        assert api.post("/api/notifications/daily", json={"confirmation": ""}).status_code == 400
        row = api.post("/api/notifications/daily", json={"confirmation": "加入通知队列"}).json()["notification"]
        assert api.get("/api/notifications").json()["notifications"][0]["data"]["status"] == "pending"
        assert api.post("/api/notifications/dispatch", json={"confirmation": "发送通知"}).status_code == 400
        snapshot = api.get("/api/export").json()
        assert all(r["kind"] != "notification_outbox" for r in snapshot["records"])
        assert api.delete(f"/api/records/{row['id']}?version=1").status_code == 409
        assert api.post(f"/api/records/{row['id']}/restore", json={"target_version": 1, "current_version": 1}).status_code == 409
        assert api.post(f"/api/notifications/{row['id']}/resolve", json={"version": 1, "action": "cancel", "confirmation": "已核对通知结果"}).status_code == 200


def test_failed_connection_known_safe_retry_can_succeed_after_configuration_fix(store):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
    first = service(store, closed_port)
    row = first.enqueue_daily()["notification"]
    assert first.dispatch()["processed"][0]["data"]["status"] == "failed"
    with smtp_fixture() as (port, received):
        fixed = service(store, port)
        failed = store.get(row["id"])
        fixed.resolve(row["id"], failed["version"], "retry", "已核对通知结果")
        assert fixed.dispatch()["processed"][0]["data"]["status"] == "sent"
        assert len(received) == 1 and store.get(row["id"])["data"]["attempts"] == 2
