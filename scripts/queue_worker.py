"""队列 worker 的命令行入口。

用法（在项目根执行）：
    python scripts/queue_worker.py                 # 常驻，轮询执行队列
    python scripts/queue_worker.py --once          # 只处理一条就退出，便于验证
    python scripts/queue_worker.py --max-tasks 3   # 处理三条后退出
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.platform.agent_capabilities import CapabilityService
from rag_tech_retriever.platform.model_connection import ModelConnection
from rag_tech_retriever.platform.queue_service import QueueService
from rag_tech_retriever.platform.queue_worker import QueueWorker, build_executors, load_env_file
from rag_tech_retriever.platform.record_store import RecordStore
from rag_tech_retriever.platform.search_service import SearchService
from rag_tech_retriever.platform.task_queue_store import TaskQueueStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="", help="应用根目录，默认脚本上级目录")
    parser.add_argument("--poll", type=float, default=3.0, help="空闲时的轮询间隔秒")
    parser.add_argument("--lease", type=int, default=900, help="任务租约秒数")
    parser.add_argument("--max-tasks", type=int, default=0, help="最多处理多少个任务，0 表示不限")
    parser.add_argument("--once", action="store_true", help="只处理一条任务就退出")
    parser.add_argument("--worker-id", default="", help="worker 标识，默认用进程号")
    parser.add_argument("--env-file", default="", help="环境文件路径，用于读取数据库连接等变量")
    args = parser.parse_args()

    if args.env_file:
        loaded = load_env_file(Path(args.env_file).expanduser())
        print(f"已从环境文件读取 {loaded} 个变量：{args.env_file}")

    root = Path(args.root).expanduser().resolve() if args.root else Path(__file__).resolve().parents[1]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    settings = ConfigLoader.load_default()
    config = ConfigLoader(settings.settings_path.parent / "web.yaml")
    store = RecordStore(str(config.get("web.table_prefix", "workspace")), config=config, pool_size=2)
    connection = ModelConnection(
        root / str(config.get("llm.connection_file", "data/local/llm-connection.json")),
        int(config.get("llm.test_timeout_seconds", 12)),
    )
    search = SearchService(
        store,
        int(config.get("web.search_limit", 10)),
        int(config.get("llm.timeout_seconds", 25)),
        int(config.get("llm.max_tokens", 800)),
        connection,
        corpus_root=root if (root / "config/corpora.yaml").exists() else None,
    )
    capabilities = CapabilityService(root, store, search, settings.env)

    queue = TaskQueueStore(store)
    if not queue.table_exists():
        print("任务队列表尚未初始化：请先运行 scripts/prepare_queue_schema.py --apply")
        return 2

    service = QueueService(queue)
    for kind, executor in build_executors(
        store=store, capabilities=capabilities, connection=connection, base=root
    ).items():
        service.register(kind, executor)

    worker = QueueWorker(service, worker_id=args.worker_id or None,
                         poll_seconds=args.poll, lease_seconds=args.lease)
    worker.install_signal_handlers()
    # --once 要的是「取一条就退出」；队列空时也退出，不能一直空转。
    worker.run(max_tasks=1 if args.once else (args.max_tasks or None),
               stop_when_idle=args.once)
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
