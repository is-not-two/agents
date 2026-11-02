"""预览或显式入队每日摘要；不安装 cron、不自动发送、不初始化数据库。"""
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
    """默认只读，入队必须显式 --enqueue；数据库表名读取已有配置。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enqueue", action="store_true")
    args = parser.parse_args()
    settings = ConfigLoader.load_default()
    web = ConfigLoader(settings.settings_path.parent / "web.yaml")
    try:
        service = NotificationService(RecordStore(web.get("web.table_prefix", "workspace"), settings))
        result = service.enqueue_daily() if args.enqueue else service.preview()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (DomainError, StorageError):
        print("摘要未完成；请检查配置、数据库就绪状态和受限账号权限", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
