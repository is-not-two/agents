"""只读生成 workspace_records 的 kind 约束迁移 SQL。

本脚本不连接数据库、不执行任何变更。正式库当前至少缺 bookmark 与 self_trait，
执行前必须停写快照、备份，并先在 8771 隔离环境预检；8770 晋级需单独授权。
"""
from __future__ import annotations

import argparse
import os
import re

from rag_tech_retriever.platform.record_store import RECORD_KINDS

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
CONFIRMATION = "执行 kind 约束迁移"


def statements(table: str) -> list[str]:
    kinds = ", ".join("'" + kind + "'" for kind in sorted(RECORD_KINDS))
    return [
        f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_kind_check;",
        f"ALTER TABLE {table} ADD CONSTRAINT {table}_kind_check CHECK (kind IN ({kinds}));",
    ]


def apply_migration(dsn: str, table: str, connect=None) -> None:
    """事务内替换约束；失败回滚。connect 可注入，便于在不连库的情况下测试。"""
    import psycopg2

    conn = (connect or psycopg2.connect)(dsn)
    try:
        with conn.cursor() as cur:
            for sql in statements(table):
                cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", default="workspace_records", help="目标表名")
    parser.add_argument("--apply", action="store_true", help="实际执行；默认只打印 SQL")
    parser.add_argument("--confirm", default="", help=f"执行时必须填写：{CONFIRMATION}")
    args = parser.parse_args()
    if not IDENTIFIER.fullmatch(args.table):
        print("FAIL: 表名只能是普通 SQL 标识符")
        return 1
    print("-- DRY RUN ONLY（默认）: 不带 --apply 时本脚本不连接数据库。")
    print(f"-- 当前代码 RECORD_KINDS 共 {len(RECORD_KINDS)} 种：{', '.join(sorted(RECORD_KINDS))}")
    print("-- 已知缺口：正式 8770 原缺 bookmark；代码另新增 self_trait、interview_prep。")
    for sql in statements(args.table):
        print(sql)
    print("-- 执行前：停写快照 + 备份 + 8771 隔离环境预检；正式晋级另需授权。")
    if not args.apply:
        return 0
    if args.confirm != CONFIRMATION:
        print(f"FAIL: 执行必须带 --confirm '{CONFIRMATION}'")
        return 1
    dsn = os.environ.get("SHILIE_MIGRATION_DSN", "")
    if not dsn:
        print("FAIL: 缺少 SHILIE_MIGRATION_DSN 环境变量，未连接数据库")
        return 1
    apply_migration(dsn, args.table)
    print("-- 已在本连接事务内完成约束替换；请自行复核数据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
