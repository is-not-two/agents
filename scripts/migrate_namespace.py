"""0-2：备份旧向量，事务迁移 namespace 主键并切换 exact；支持独立数据库恢复。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg2.extras

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient
from rag_tech_retriever.rag.vector_store.schema import validate_table_name


def migrate(backup: Path, restore: bool = False) -> dict:
    """备份/事务迁移；恢复前保存当前数据，拒绝覆盖包含其他域的表。"""
    cfg = ConfigLoader.load_default()
    table = validate_table_name(str(cfg.get("vector_store.table_name", "rag_chunks")))
    client = PgVectorClient()
    client.connect()
    conn = client._conn
    conn.autocommit = False
    try:
        with conn, conn.cursor() as cur:
            cur.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
            cur.execute(f"SELECT row_to_json(r) FROM {table} r ORDER BY chunk_id")
            current = [row[0] for row in cur.fetchall()]
            cur.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname=current_schema() AND tablename=%s",
                (table,),
            )
            indexes = cur.fetchall()
            if restore:
                payload = json.loads(backup.read_text(encoding="utf-8"))
                if payload["table"] != table:
                    raise ValueError("备份表名不匹配")
                if any(row.get("namespace", "tech_doc") != "tech_doc" for row in current):
                    raise ValueError("已有其他域数据，拒绝整表恢复；请先人工规划迁移")
                rescue = backup.with_name("vector_before_restore.json")
                rescue.write_text(
                    json.dumps(
                        {"table": table, "rows": current, "indexes": indexes}, ensure_ascii=False
                    ),
                    encoding="utf-8",
                )
                cur.execute(f"DELETE FROM {table}")
                cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_pkey")
                cur.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS namespace")
                cur.execute(f"ALTER TABLE {table} ADD PRIMARY KEY (chunk_id)")
                rows = payload["rows"]
                values = [
                    (
                        r["chunk_id"],
                        r["source_file"],
                        r["heading_path"],
                        r["content"],
                        r["status_marker"],
                        r["embedding"],
                    )
                    for r in rows
                ]
                psycopg2.extras.execute_values(
                    cur,
                    f"INSERT INTO {table} "
                    "(chunk_id,source_file,heading_path,content,status_marker,embedding) VALUES %s",
                    values,
                )
                for _, definition in payload["indexes"]:
                    if "USING ivfflat" in definition or "USING hnsw" in definition:
                        cur.execute(definition)
                return {"restored": len(rows), "rescue": str(rescue)}
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_text(
                    json.dumps(
                        {"table": table, "rows": current, "indexes": indexes}, ensure_ascii=False
                    ),
                    encoding="utf-8",
                )
            cur.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                "namespace TEXT NOT NULL DEFAULT 'tech_doc'"
            )
            cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_pkey")
            cur.execute(f"ALTER TABLE {table} ADD PRIMARY KEY(namespace, chunk_id)")
            for name, definition in indexes:
                if "USING ivfflat" in definition or "USING hnsw" in definition:
                    cur.execute(f"DROP INDEX {validate_table_name(name)}")
            return {"migrated": len(current), "backup": str(backup), "index_type": "exact"}
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backup", type=Path, default=Path("output/stages/20261012-01-core/vector_before.json")
    )
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(args.backup, args.restore), ensure_ascii=False))
