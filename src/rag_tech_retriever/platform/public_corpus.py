"""Pinned public snapshots, verified text/vector bundles and non-destructive namespace IO."""

import hashlib
import json
import math
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from psycopg2.extras import execute_values

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.rag.vector_store.pgvector_client import to_vector_literal
from rag_tech_retriever.rag.vector_store.schema import validate_table_name

MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 10000
TEXT_FIELDS = ("chunk_id", "source_file", "heading_path", "content", "status_marker")


def fingerprint(value: object) -> str:
    """Canonical JSON SHA binds text, IDs, sources and values without timestamp noise."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_json(path: Path) -> dict:
    """Bounded UTF-8 data only; duplicate JSON keys are rejected."""
    if path.stat().st_size > MAX_BYTES:
        raise DomainError("公开语料文件超过大小限制")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise DomainError("公开语料JSON包含重复键")
            value[key] = item
        return value
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise DomainError("公开语料不是有效UTF-8 JSON") from None
    if not isinstance(value, dict): raise DomainError("公开语料顶层必须是对象")
    return value


def approved_manifest(root: Path) -> dict:
    """The administrator-reviewed source/chunk hashes are shipped as source config."""
    value = read_json(root / "config/public-sources.json")
    if (type(value.get("schema")) is not int or value["schema"] != 1 or not isinstance(value.get("sources"), dict)
            or not isinstance(value.get("chunk_hashes"), dict) or not isinstance(value.get("embedding"), dict)
            or type(value["embedding"].get("dim")) is not int or not 1 <= value["embedding"]["dim"] <= 2000):
        raise DomainError("公开来源审批清单无效")
    return value


def validate_bundle(value: dict, approval: dict, *, vectors: bool = False) -> dict:
    """A public label alone is insufficient: every text row must match approved hashes."""
    if (not isinstance(value, dict) or set(value) != {"schema", "namespace", "embedding", "sources", "rows", "content_sha256", "rows_sha256"}
            or type(value["schema"]) is not int or value["schema"] != 1 or value["namespace"] != "public_docs"
            or value["sources"] != approval["sources"] or value["embedding"] != approval["embedding"]
            or not isinstance(value["rows"], list) or not 1 <= len(value["rows"]) <= MAX_ROWS):
        raise DomainError("公开语料域、来源、模型或结构不符合审批清单")
    seen, text_rows = set(), []
    dim = value["embedding"]["dim"]
    for row in value["rows"]:
        if not isinstance(row, dict) or set(row) not in (set(TEXT_FIELDS), {*TEXT_FIELDS, "embedding"}):
            raise DomainError("公开语料行字段无效")
        if any(not isinstance(row[key], str) or not row[key].strip() for key in TEXT_FIELDS):
            raise DomainError("公开语料行含空字段")
        text = {key: row[key] for key in TEXT_FIELDS}
        if (row["chunk_id"] in seen or row["source_file"] not in approval["sources"]
                or approval["chunk_hashes"].get(row["chunk_id"]) != fingerprint(text)):
            raise DomainError("公开内容与审批SHA不符，不能改名混入私有内容")
        seen.add(row["chunk_id"]); text_rows.append(text)
        embedding = row.get("embedding")
        if (vectors or embedding is not None) and (not isinstance(embedding, list) or len(embedding) != dim
                or any(type(x) not in (int, float) or not -1e6 < x < 1e6 or not math.isfinite(x) for x in embedding)
                or not any(embedding)):
            raise DomainError("向量缺失、维度错误、零向量或含非有限数")
    if fingerprint(text_rows) != value["content_sha256"] or fingerprint(value["rows"]) != value["rows_sha256"]:
        raise DomainError("公开语料校验和不符")
    return value


def bundle(rows: list[dict], approval: dict) -> dict:
    """Create and validate a deterministic bundle; no private namespace conversion."""
    value = {"schema": 1, "namespace": "public_docs", "embedding": deepcopy(approval["embedding"]),
             "sources": deepcopy(approval["sources"]), "rows": deepcopy(rows),
             "content_sha256": fingerprint([{key: row[key] for key in TEXT_FIELDS} for row in rows]),
             "rows_sha256": fingerprint(rows)}
    return validate_bundle(value, approval)


def write_fresh(path: Path, value: dict) -> dict:
    """Never replace an existing data file; repeatable identical installation is a no-op."""
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_BYTES: raise DomainError("公开语料包过大")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw: raise DomainError("拒绝覆盖不同的已有语料文件")
    else:
        temp = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".public-corpus-", dir=path.parent, delete=False) as stream:
                temp = Path(stream.name); stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            try:
                os.link(temp, path)  # Atomic publish, never replace an existing target.
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != raw: raise DomainError("并发安装内容不同，拒绝覆盖") from None
        finally:
            if temp is not None: temp.unlink()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": len(raw)}


def import_vectors(client, table: str, value: dict, approval: dict) -> dict:
    """One transaction; only public_docs, never DDL/DELETE or overwrite differing rows."""
    validate_bundle(value, approval, vectors=True); table = validate_table_name(table)
    client.connect(); connection = client._conn
    # PgVectorClient normally autocommits. Explicit transaction is restored even on failure.
    previous = connection.autocommit; connection.autocommit = False
    try:
        with connection, connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (table + ":public_docs:import",))
            cur.execute(f"SELECT chunk_id,source_file,heading_path,content,status_marker,embedding::text FROM {table} WHERE namespace=%s FOR UPDATE", ("public_docs",))
            existing = {row[0]: row for row in cur.fetchall()}
            for row in value["rows"]:
                if row["chunk_id"] in existing:
                    old = existing[row["chunk_id"]]
                    if tuple(row[key] for key in TEXT_FIELDS) != old[:5] or any(
                        abs(a-b) > 1e-5 for a,b in zip(row["embedding"], json.loads(old[5]), strict=True)
                    ): raise DomainError("现有公开向量与导入不同，拒绝覆盖；需要独立审查迁移")
            values = [("public_docs", *(row[k] for k in TEXT_FIELDS), to_vector_literal(row["embedding"])) for row in value["rows"] if row["chunk_id"] not in existing]
            sql = (f"INSERT INTO {table} (namespace,chunk_id,source_file,heading_path,content,status_marker,embedding) VALUES %s "
                   "ON CONFLICT(namespace,chunk_id) DO NOTHING RETURNING chunk_id")
            inserted = len(execute_values(cur, sql, values, page_size=64, fetch=True)) if values else 0
            # Check collisions from writers that did not take our advisory lock.
            cur.execute(f"SELECT chunk_id,source_file,heading_path,content,status_marker,embedding::text FROM {table} WHERE namespace=%s", ("public_docs",))
            final = {row[0]: row for row in cur.fetchall()}
            for row in value["rows"]:
                saved = final[row["chunk_id"]]
                if tuple(row[key] for key in TEXT_FIELDS) != saved[:5] or any(
                    abs(a-b) > 1e-5 for a,b in zip(row["embedding"], json.loads(saved[5]), strict=True)
                ): raise DomainError("导入期间出现不同的并发记录，事务未提交")
        return {"namespace": "public_docs", "inserted": inserted, "unchanged": len(value["rows"])-inserted, "deleted": 0}
    finally:
        connection.autocommit = previous


def export_vectors(client, table: str, approval: dict) -> dict:
    """No caller-supplied namespace; contaminated rows fail validation before output."""
    table = validate_table_name(table)
    rows = client.fetch_all(f"SELECT chunk_id,source_file,heading_path,content,status_marker,embedding::text AS embedding FROM {table} WHERE namespace=%s ORDER BY chunk_id", ("public_docs",))
    # Database locale collation may differ from Python's snapshot ordering.
    rows.sort(key=lambda row: row["chunk_id"])
    for row in rows: row["embedding"] = json.loads(row["embedding"])
    return validate_bundle(bundle(rows, approval), approval, vectors=True)
