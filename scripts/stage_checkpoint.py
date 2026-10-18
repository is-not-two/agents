"""阶段日志/源码回滚命令。rollback 默认仅预检，--apply 才修改源码；数据库另行恢复。"""

import argparse
import json

from rag_tech_retriever.common.config_loader import PROJECT_ROOT
from rag_tech_retriever.common.stage_journal import StageJournal


def main() -> None:
    """输出稳定 JSON 供人工或 agent 检查，不隐藏回滚冲突。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "start", "finish", "rollback"])
    parser.add_argument("--id")
    parser.add_argument("--title", default="新阶段")
    parser.add_argument("--objective", default="")
    parser.add_argument("--completed", action="append", default=[])
    parser.add_argument("--issue", action="append", default=[])
    parser.add_argument("--verified", action="append", default=[])
    parser.add_argument("--attention", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    journal = StageJournal(PROJECT_ROOT, PROJECT_ROOT / "output/stages")
    if args.command == "list":
        result = journal.list()
    elif args.command == "start":
        result = journal.start(args.title, args.objective)
    elif not args.id:
        parser.error("该命令必须指定 --id")
    elif args.command == "finish":
        result = journal.finish(
            args.id,
            args.completed,
            args.issue,
            args.verified,
            "attention" if args.attention else "passed",
        )
    else:
        result = journal.rollback(args.id, args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
