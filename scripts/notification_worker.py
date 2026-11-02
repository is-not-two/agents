"""有限批次通知 worker；配置启用且显式确认后才执行 SMTP 外发。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.notifications import NotificationService
from rag_tech_retriever.platform.record_store import RecordStore, StorageError


def main() -> int:
    """默认配置摘要不含任何凭据；无守护进程或无限重试循环。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-send", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    settings = ConfigLoader.load_default()
    web = ConfigLoader(settings.settings_path.parent / "web.yaml")
    try:
        service = NotificationService(RecordStore(web.get("web.table_prefix", "workspace"), settings))
        result = service.dispatch(args.limit) if args.confirm_send else {"sending": False, "settings": service.public()}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (DomainError, StorageError):
        print("通知未完成；请查看队列状态并核对配置，勿盲目重发", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
