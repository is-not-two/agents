"""Restore drills use only generated tables, temporary verifier files and fake secrets."""

import base64
import json
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.api.routes import private
from rag_tech_retriever.platform import private_backup as backup
from rag_tech_retriever.platform import private_store as crypto
from rag_tech_retriever.platform.record_store import RecordStore, StorageError

ARCHIVE_PASSWORD = "test-only-backup-password"
VAULT_PASSWORD = "test-only-vault-password"


@pytest.fixture
def drill(tmp_path):
    stores = [RecordStore("qa_private_" + uuid4().hex[:10]) for _ in range(2)]
    try:
        for store in stores:
            store.ensure_schema()
        salt, digest = crypto.make_verifier(VAULT_PASSWORD)
        meta = {"salt": base64.b64encode(salt).decode(), "digest": digest,
                "recovery": crypto.recovery_digest(VAULT_PASSWORD, salt),
                "created_at": "2026-10-20T10:00:00+08:00"}
        source_meta, target_meta = tmp_path / "source.json", tmp_path / "target.json"
        source_meta.write_text(json.dumps(meta), encoding="utf-8")
        source, target = stores
        source.save("knowledge", {"title": "not included"})
        row = source.save("wish", {"cipher": crypto.encrypt_json({"title": "虚拟愿望"}, VAULT_PASSWORD)})
        source.save("wish", {"cipher": crypto.encrypt_json({"title": "虚拟愿望更新"}, VAULT_PASSWORD)},
                    row["id"], row["version"])
        diary = source.save("diary", {"cipher": crypto.encrypt_json({"body": "虚拟日记"}, VAULT_PASSWORD)})
        source.delete(diary["id"], diary["version"])
        payload = backup.capture(source, source_meta)
        yield source, target, target_meta, payload
    finally:
        for store in stores:
            with store.transaction() as cur:
                cur.execute(f"DROP TABLE IF EXISTS {store.versions}")
                cur.execute(f"DROP TABLE IF EXISTS {store.records}")


def test_encrypted_roundtrip_with_full_history_and_web_unlock(drill, tmp_path, monkeypatch):
    source, target, meta, payload = drill
    public = target.save("knowledge", {"title": "public sentinel"})
    archive = tmp_path / "backup.private.json"
    backup.write_archive(payload, archive, ARCHIVE_PASSWORD)
    assert "虚拟" not in archive.read_text(encoding="utf-8")
    assert payload["vault_meta"]["digest"] not in archive.read_text(encoding="utf-8")
    opened = backup.read_archive(archive, ARCHIVE_PASSWORD)
    assert backup.restore(target, meta, opened) == {"records": 2, "versions": 4, "deleted": 1}
    for row in payload["records"]:
        assert target.get(row["id"], include_deleted=True) == source.get(row["id"], include_deleted=True)
        assert target.history(row["id"]) == source.history(row["id"])
    assert target.get(public["id"]) == public
    monkeypatch.setattr(private, "_meta_path", lambda _: meta)
    with TestClient(create_app(target, tmp_path / "app", token="")) as client:
        assert client.post("/api/private/session", json={"password": "wrong"}).status_code == 401
        ticket = client.post("/api/private/session", json={"password": VAULT_PASSWORD}).json()["ticket"]
        wishes = client.get("/api/private/wish", params={"ticket": ticket}).json()
        assert wishes[0]["data"]["title"] == "虚拟愿望更新"
        assert client.get("/api/private/diary", params={"ticket": ticket}).json() == []
    assert backup.capture(target, meta)["versions"] == payload["versions"]


def test_wrong_password_tamper_limits_and_no_overwrite(drill, tmp_path):
    _, target, meta, payload = drill
    path = tmp_path / "backup.json"
    backup.write_archive(payload, path, ARCHIVE_PASSWORD)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        backup.write_archive(payload, path, ARCHIVE_PASSWORD)
    assert path.read_bytes() == original
    with pytest.raises(ValueError):
        backup.read_archive(path, "wrong")
    with pytest.raises(ValueError):
        backup.read_archive(path, ARCHIVE_PASSWORD, maximum=10)
    sealed = json.loads(original)
    blob = bytearray(base64.b64decode(sealed["cipher"]["data"]))
    blob[-1] ^= 1
    sealed["cipher"]["data"] = base64.b64encode(blob).decode()
    path.write_text(json.dumps(sealed), encoding="utf-8")
    with pytest.raises(ValueError):
        backup.read_archive(path, ARCHIVE_PASSWORD)
    path.write_bytes(original[:40])
    with pytest.raises(ValueError):
        backup.read_archive(path, ARCHIVE_PASSWORD)
    assert not meta.exists()
    assert target.list("wish") == []


@pytest.mark.parametrize("mode", ["kind", "duplicate", "history", "state", "version", "metadata"])
def test_invalid_payload_never_mutates_target(drill, mode):
    _, target, meta, payload = drill
    damaged = deepcopy(payload)
    if mode == "kind":
        damaged["records"][0]["kind"] = "knowledge"
    elif mode == "duplicate":
        damaged["records"].append(damaged["records"][0])
    elif mode == "history":
        damaged["versions"].pop()
    elif mode == "state":
        damaged["records"][0]["deleted"] = "false"
    elif mode == "version":
        damaged["records"][0]["version"] = 10**12
    else:
        damaged["vault_meta"]["salt"] = "invalid"
    with pytest.raises(ValueError):
        backup.restore(target, meta, damaged)
    assert not meta.exists()
    assert target.list("wish") == []


@pytest.mark.parametrize("mode", ["nonempty", "collision", "different_meta"])
def test_refuse_unsafe_destination(drill, mode):
    _, target, meta, payload = drill
    if mode == "nonempty":
        target.save("wish", {"cipher": {"test": "sentinel"}})
    elif mode == "collision":
        with target.transaction() as cur:
            target._save(cur, "knowledge", {"title": "sentinel"}, payload["records"][0]["id"], None)
    else:
        meta.write_text("{}", encoding="utf-8")
    before = target.export()
    with pytest.raises(StorageError):
        backup.restore(target, meta, payload)
    assert target.export() == before
    if mode != "different_meta":
        assert not meta.exists()


def test_database_failure_rolls_back_all_rows_and_same_archive_can_retry(drill, monkeypatch):
    _, target, meta, payload = drill
    transaction = target.transaction

    @contextmanager
    def failing():
        with transaction() as cur:
            yield cur
            raise StorageError("injected failure before commit")

    monkeypatch.setattr(target, "transaction", failing)
    with pytest.raises(StorageError):
        backup.restore(target, meta, payload)
    monkeypatch.setattr(target, "transaction", transaction)
    assert target.list("wish") == []
    assert meta.exists()  # Deliberately retained: no unsafe deletion on uncertain DB outcome.
    assert backup.restore(target, meta, payload)["records"] == 2


def test_refuse_weak_crypto_and_short_backup_password(drill, tmp_path, monkeypatch):
    payload = drill[3]
    with pytest.raises(ValueError):
        backup.write_archive(payload, tmp_path / "short.json", "short")
    monkeypatch.setattr(crypto, "have_strong_crypto", lambda: False)
    with pytest.raises(ValueError):
        backup.write_archive(payload, tmp_path / "weak.json", ARCHIVE_PASSWORD)
    assert not (tmp_path / "weak.json").exists()


def test_file_publish_failure_leaves_no_partial_archive(drill, tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("injected filesystem publication failure")

    monkeypatch.setattr(backup.os, "link", fail)
    path = tmp_path / "unpublished.json"
    with pytest.raises(OSError):
        backup.write_archive(drill[3], path, ARCHIVE_PASSWORD)
    assert not path.exists()
    assert list(tmp_path.glob(".private-backup-*")) == []


def test_cli_inspect_uses_only_fake_archive_and_reports_counts(drill, tmp_path, monkeypatch, capsys):
    import importlib.util
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts/private_backup.py"
    spec = importlib.util.spec_from_file_location("qa_private_backup_cli", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    archive = tmp_path / "cli.private.json"
    backup.write_archive(drill[3], archive, ARCHIVE_PASSWORD)
    monkeypatch.setattr(sys, "argv", [str(script), "inspect", str(archive)])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: ARCHIVE_PASSWORD)
    assert cli.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["records"] == 2
    assert output["versions"] == 4
    assert "虚拟" not in json.dumps(output, ensure_ascii=False)


@pytest.mark.parametrize("mode", ["missing_archive", "running_web"])
def test_cli_rejects_invalid_operation_before_password_prompt(tmp_path, monkeypatch, capsys, mode):
    import importlib.util
    import socket
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts/private_backup.py"
    spec = importlib.util.spec_from_file_location("qa_private_backup_guard", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    def no_prompt(*args):
        raise AssertionError("invalid operation must not ask for any password")

    monkeypatch.setattr(cli.getpass, "getpass", no_prompt)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        config = tmp_path / "config"
        config.mkdir()
        (config / "web.yaml").write_text(
            "web:\n  host: 127.0.0.1\n  port: " + str(sock.getsockname()[1]), encoding="utf-8")
        monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
        command = "inspect" if mode == "missing_archive" else "export"
        monkeypatch.setattr(sys, "argv", [str(script), command, str(tmp_path / "absent.json")])
        assert cli.main() == 1
    assert json.loads(capsys.readouterr().err)["status"] == "failed"
