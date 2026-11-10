"""只读生成 workspace_records 的 kind 约束迁移 SQL（不连库、不执行变更）。

默认 DRY RUN：只打印 SQL，把约束对齐到代码当前的 RECORD_KINDS。
`--apply` 需显式确认语与 SHILIE_MIGRATION_DSN，且必须在停写快照 + 备份 +
隔离环境预检之后执行；8770 晋级另需授权。

注意：各库现状不同，不能按固定缺口推断。已核对过的事实（2026-11-10）：
- 旧 preview 库（5432/shilie_preview_20261103）为 19 种，缺 interview_prep；
- 8771 隔离库（55433/shilie_preview_20261104）为 21 种，已含 interview_prep，
  但多一个代码里不存在的 self_trait。
执行前必须先查目标库的实际约束定义。
"""
from __future__ import annotations

import argparse
import os
import re

from rag_tech_retriever.platform.record_store import RECORD_KINDS

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
CONFIRMATION = "执行 kind 约束迁移"
CHECK_DEF_SQL = (
    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conname='workspace_records_kind_check'"
)


def statements(table: str) -> list[str]:
    kinds = ", ".join("'" + kind + "'" for kind in sorted(RECORD_KINDS))
    return [
        f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_kind_check;",
        f"ALTER TABLE {table} ADD CONSTRAINT {table}_kind_check CHECK (kind IN ({kinds}));",
    ]


def apply_migration(dsn: str, table: str, connect=None) -> None:
    """事务内替换约束；失败回滚。connect 可注入便于离线测试。"""
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
    print(f"-- 执行前先核对目标库实际约束：{CHECK_DEF_SQL};")
    for sql in statements(args.table):
        print(sql)
    print("-- 执行前：停写快照 + 备份 + 隔离环境预检；正式晋级另需授权。")
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
