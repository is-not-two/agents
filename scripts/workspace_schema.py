"""Check workspace schema by default; migration is an explicit administrator action."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rag_tech_retriever.common.config_loader import ConfigError, ConfigLoader
from rag_tech_retriever.platform.record_store import RecordStore, StorageError


def main() -> int:
    """Never install software, grant privileges, delete data or infer a target database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "migrate"], nargs="?", default="check")
    parser.add_argument("--prefix", help="Workspace table prefix, default from web.yaml")
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--runtime-role", action="store_true", help="Also require restricted production runtime privileges")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    config = ConfigLoader.load_default()
    web = ConfigLoader(config.settings_path.parent / "web.yaml")
    store = RecordStore(args.prefix or str(web.get("web.table_prefix", "workspace")), config)
    with store.transaction() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT current_database() AS database")
        actual = cur.fetchone()["database"]
    if actual != args.expected_database or str(config.env("POSTGRES_DB", "rag_tech_doc")) != args.expected_database:
        raise StorageError("数据库身份与显式预期不符；未迁移")
    if args.action == "migrate":
        if args.runtime_role: raise StorageError("迁移与运行账号验权是两项不同操作")
        result = store.migrate_schema(args.confirm)
    else:
        if args.confirm: raise StorageError("check不接受迁移确认，不会执行DDL")
        result = store.verify_schema(require_runtime_role=args.runtime_role)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConfigError, StorageError) as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr); raise SystemExit(1) from None
