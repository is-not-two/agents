"""只读统计或显式保存/入队周报；默认不使用模型、不发送邮件。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.model_connection import ModelConnection
from rag_tech_retriever.platform.notifications import NotificationService
from rag_tech_retriever.platform.record_store import RecordStore, StorageError
from rag_tech_retriever.platform.weekly_report import WeeklyReport


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", default="")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--enqueue", action="store_true")
    args = parser.parse_args()
    try:
        settings = ConfigLoader.load_default()
        web = ConfigLoader(settings.settings_path.parent / "web.yaml")
        root = settings.settings_path.parent.parent
        store = RecordStore(web.get("web.table_prefix", "workspace"), settings)
        weekly = WeeklyReport(
            root,
            store,
            ModelConnection(
                root / web.get("llm.connection_file", "data/local/llm-connection.json")
            ),
        )
        result = (
            weekly.generate(args.day, "statistics", "生成并保存周报")
            if args.save or args.enqueue
            else weekly.report(args.day)
        )
        if args.enqueue:
            result = NotificationService(store).enqueue_weekly(result)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (DomainError, StorageError):
        print("周报未完成；请核对日期、配置和受限数据库权限，未自动发送或调用模型", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
