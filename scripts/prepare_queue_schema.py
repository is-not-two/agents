"""任务队列表的迁移脚本：默认只打印要做什么，不改库。

为什么要单独迁移：生产运行账号没有 CREATE 权限，表必须由库属主预先建好；
这个脚本是管理员路径，与 kind 约束迁移是同一套流程。

用法（在项目根执行）：
    python scripts/prepare_queue_schema.py                     # 只看要做什么
    python scripts/prepare_queue_schema.py --apply --confirm "确认创建任务队列表"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import psycopg2

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.platform.task_queue_store import DDL_STATEMENTS

CONFIRM_TEXT = "确认创建任务队列表"


def dsn(settings: ConfigLoader) -> dict:
    """连接参数；敏感值只从环境变量读取。"""
    return {
        "host": settings.env("POSTGRES_HOST", "127.0.0.1"),
        "port": settings.env("POSTGRES_PORT", "5432"),
        "dbname": settings.env("POSTGRES_DB", "rag_tech_doc"),
        "user": settings.env("POSTGRES_USER", "rag"),
        "password": settings.env("POSTGRES_PASSWORD", ""),
        "connect_timeout": 5,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="workspace", help="工作台表前缀，默认 workspace")
    parser.add_argument("--apply", action="store_true", help="真正执行建表")
    parser.add_argument("--confirm", default="", help=f"执行时必须填写：{CONFIRM_TEXT}")
    args = parser.parse_args()

    settings = ConfigLoader.load_default()
    config = ConfigLoader(settings.settings_path.parent / "web.yaml")
    prefix = str(config.get("web.table_prefix", args.prefix))
    table = prefix + "_task_jobs"

    statements = [statement.format(table=table) for statement in DDL_STATEMENTS]
    print(f"目标表：{table}")
    for statement in statements:
        print("-" * 60)
        print(statement.strip())

    if not args.apply:
        print("-" * 60)
        print("以上为将要执行的内容；加 --apply 并填写确认文字后才会真正建表。")
        return 0

    if args.confirm != CONFIRM_TEXT:
        print(f"未执行：请填写确认文字「{CONFIRM_TEXT}」")
        return 2

    conn = psycopg2.connect(**dsn(settings))
    try:
        with conn, conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
        conn.commit()
    except psycopg2.Error as exc:
        print(f"执行失败：{exc}")
        return 1
    finally:
        conn.close()
    print(f"已创建或升级：{table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
