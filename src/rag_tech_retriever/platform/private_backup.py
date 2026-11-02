"""Password-encrypted private archives; restore only into an empty private area.

The database transaction is atomic. The verifier file is installed first and retained
on a database failure, so an identical archive can safely be retried. Stop the app
before export/restore: a filesystem and PostgreSQL cannot share one transaction.
"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from psycopg2.extras import Json

from rag_tech_retriever.platform import private_store as crypto
from rag_tech_retriever.platform.record_store import RecordStore, StorageError

FORMAT = "shilie-private-backup"
PRIVATE_KINDS = ["wish", "diary"]
DEFAULT_MAX_BYTES = 67_108_864


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _read(path: Path, maximum: int) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("备份或元数据超过大小限制")
    return raw


def _new_file(path: Path, raw: bytes) -> None:
    """Publish a complete file atomically without replacing an existing path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".private-backup-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-filesystem hard-link creation is exclusive on Windows and POSIX.
        # Unsupported filesystems fail safely rather than reverting to overwrite.
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _timestamp(value: object) -> None:
    if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("时间格式错误")


def validate(payload: dict) -> None:
    """Validate the complete archive before touching destination state."""
    try:
        if payload["format"] != FORMAT or payload["version"] != 1:
            raise ValueError("备份版本不支持")
        meta = payload["vault_meta"]
        if len(base64.b64decode(meta["salt"], validate=True)) != 16:
            raise ValueError("校验盐格式错误")
        for field in ("digest", "recovery"):
            if not re.fullmatch(r"[a-f0-9]{64}", meta[field]):
                raise ValueError("校验信息格式错误")
        _timestamp(meta["created_at"])
        records, versions = payload["records"], payload["versions"]
        if not isinstance(records, list) or not isinstance(versions, list):
            raise TypeError("记录格式错误")
        current, history = {}, {}
        for row in records:
            record_id = row["id"]
            if not isinstance(record_id, str) or not 0 < len(record_id) <= 256:
                raise ValueError("记录 ID 格式错误")
            if record_id in current or row["kind"] not in PRIVATE_KINDS:
                raise ValueError("重复 ID 或非私密记录")
            current[record_id] = row
            _timestamp(row["updated_at"])
        for row in versions:
            key = (row["record_id"], row["version"])
            if key in history or key[0] not in current or not isinstance(row["action"], str):
                raise ValueError("历史版本格式错误")
            history[key] = row
        for row in [*records, *versions]:
            if type(row["version"]) is not int or row["version"] < 1:
                raise ValueError("版本号格式错误")
            if type(row["deleted"]) is not bool or not isinstance(row["data"], dict):
                raise ValueError("记录状态格式错误")
            if set(row["data"]) != {"cipher"} or not isinstance(row["data"]["cipher"], dict):
                raise ValueError("备份只能包含私密密文")
            _timestamp(row["created_at"])
        for record_id, row in current.items():
            actual = {version for key, version in history if key == record_id}
            if row["version"] != len(actual) or actual != set(range(1, len(actual) + 1)):
                raise ValueError("历史版本不完整")
            latest = history[(record_id, row["version"])]
            if latest["data"] != row["data"] or latest["deleted"] != row["deleted"]:
                raise ValueError("当前记录与历史不一致")
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("私密备份结构不正确") from exc


def capture(store: RecordStore, vault_file: Path) -> dict:
    """Read ciphertext and its full history in one consistent DB snapshot."""
    meta_raw = _read(vault_file, 65_536)
    with store.transaction() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cur.execute(f"SELECT * FROM {store.records} WHERE kind=ANY(%s) ORDER BY id", (PRIVATE_KINDS,))
        records = [store._serialize(row) for row in cur.fetchall()]
        cur.execute(
            f"SELECT v.* FROM {store.versions} v JOIN {store.records} r ON r.id=v.record_id "
            "WHERE r.kind=ANY(%s) ORDER BY v.record_id,v.version", (PRIVATE_KINDS,),
        )
        versions = [store._serialize(row) for row in cur.fetchall()]
    if _read(vault_file, 65_536) != meta_raw:
        raise ValueError("备份期间口令元数据发生变化，请停止网页后重试")
    payload = {"format": FORMAT, "version": 1, "vault_meta": json.loads(meta_raw),
               "records": records, "versions": versions}
    validate(payload)
    return payload


def write_archive(payload: dict, path: Path, password: str, maximum: int = DEFAULT_MAX_BYTES) -> None:
    """Seal a new archive with AES-GCM and a separate backup password."""
    if not crypto.have_strong_crypto():
        raise ValueError("私密备份要求安装 cryptography（AES-GCM）")
    if len(password) < 12:
        raise ValueError("备份口令至少 12 个字符")
    validate(payload)
    if len(_json_bytes(payload)) > maximum:
        raise ValueError("私密数据超过备份大小限制")
    sealed = {"format": FORMAT, "version": 1, "cipher": crypto.encrypt_json(payload, password)}
    raw = _json_bytes(sealed)
    if len(raw) > maximum:
        raise ValueError("加密备份超过大小限制")
    _new_file(path, raw)


def read_archive(path: Path, password: str, maximum: int = DEFAULT_MAX_BYTES) -> dict:
    """Authenticate before parsing contents; do not print metadata or ciphertext."""
    if not crypto.have_strong_crypto():
        raise ValueError("私密备份要求安装 cryptography（AES-GCM）")
    try:
        sealed = json.loads(_read(path, maximum))
        if sealed["format"] != FORMAT or sealed["version"] != 1:
            raise ValueError("备份版本不支持")
        if sealed["cipher"]["alg"] != "aes-gcm":
            raise ValueError("私密备份必须使用 AES-GCM")
        payload = crypto.decrypt_json(sealed["cipher"], password)
        validate(payload)
        return payload
    except (KeyError, TypeError, UnicodeError, AttributeError) as exc:
        raise ValueError("私密备份格式不正确") from exc


def summary(payload: dict) -> dict:
    """Counts only, never private titles, bodies, IDs or verifier information."""
    return {"records": len(payload["records"]), "versions": len(payload["versions"]),
            "deleted": sum(row["deleted"] for row in payload["records"])}


def restore(store: RecordStore, vault_file: Path, payload: dict) -> dict:
    """Restore exact ciphertext/history to an empty private area, preserving public data."""
    validate(payload)
    with store.transaction() as cur:
        cur.execute(f"LOCK TABLE {store.records}, {store.versions} IN EXCLUSIVE MODE")
        cur.execute(f"SELECT id,kind FROM {store.records}")
        existing = {row["id"]: row["kind"] for row in cur.fetchall()}
        if any(kind in PRIVATE_KINDS for kind in existing.values()):
            raise StorageError("目标私密区非空，禁止覆盖；请使用空的隔离目标")
        if existing.keys() & {row["id"] for row in payload["records"]}:
            raise StorageError("私密备份 ID 与公共记录冲突，禁止覆盖")
        try:
            _new_file(vault_file, _json_bytes(payload["vault_meta"]))
        except FileExistsError:
            if json.loads(_read(vault_file, 65_536)) != payload["vault_meta"]:
                raise StorageError("目标口令元数据不同，禁止覆盖") from None
        for row in payload["records"]:
            cur.execute(
                f"INSERT INTO {store.records} (id,kind,version,data,deleted,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (row["id"], row["kind"], row["version"], Json(row["data"]), row["deleted"],
                 row["created_at"], row["updated_at"]),
            )
        for row in payload["versions"]:
            cur.execute(
                f"INSERT INTO {store.versions} (record_id,version,data,deleted,action,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (row["record_id"], row["version"], Json(row["data"]), row["deleted"],
                 row["action"], row["created_at"]),
            )
    return summary(payload)
