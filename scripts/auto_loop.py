"""跑通一条最简单的自动流程：给目标 → 模型改代码 → 跑门禁 → 通过或回退。

用法（在项目根执行）：
    python scripts/auto_loop.py --repo /path/to/repo \
        --task "让 tests/test_calc.py 通过" \
        --gate "python -m pytest -q tests/test_calc.py" \
        --tier patch

模型连接复用网页里配置好的那份（默认 <root>/data/local/llm-connection.json），
没有则读环境变量 LLM_*。所有改动发生在 worktree 副本里，主目录不受影响。
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag_tech_retriever.platform.aider_attempt import AiderAttempt
from rag_tech_retriever.platform.coding_loop import Budget, CodingLoop
from rag_tech_retriever.platform.model_attempt import EditingModel
from rag_tech_retriever.platform.model_connection import ModelConnection
from rag_tech_retriever.platform.opencode_attempt import OpenCodeAttempt

DEFAULT_READONLY = "tests,test,conftest.py,pyproject.toml,requirements.txt,setup.cfg"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="被修改的仓库根（必须已 git init）")
    parser.add_argument("--task", required=True, help="要它做成什么")
    parser.add_argument("--gate", required=True, help="验收命令，退出码 0 视为通过")
    parser.add_argument("--tier", default="patch", choices=["patch", "feature", "epic"])
    parser.add_argument("--isolation", default="auto", choices=["auto", "worktree", "clone"],
                        help="auto：opencode 用 clone（worktree 里会卡住），其余用 worktree")
    parser.add_argument("--worktree", default="", help="副本目录，默认与被改仓库同级")
    parser.add_argument("--root", default="", help="读取模型连接配置的根，默认当前目录")
    parser.add_argument("--readonly", default=DEFAULT_READONLY, help="禁止修改的路径，逗号分隔")
    parser.add_argument("--rounds", type=int, default=0, help="覆盖档位轮次上限")
    parser.add_argument("--keep", action="store_true", help="保留副本，便于人工查看")
    parser.add_argument("--engine", default="model", choices=["model", "aider", "opencode"],
                        help="model=模型直接返回整文件；aider/opencode=交给成熟 harness 改")
    parser.add_argument("--aider-bin", default="aider", help="aider 可执行文件路径")
    parser.add_argument("--opencode-bin", default="opencode", help="opencode 可执行文件路径")
    parser.add_argument("--opencode-port", type=int, default=0,
                        help="opencode 服务端口；0 表示自动挑空闲端口")
    parser.add_argument("--opencode-home", default="", help="opencode 的 HOME（配置与状态）")
    parser.add_argument("--opencode-supervisor", default="", choices=["", "systemd"],
                        help="systemd：交给 systemd-run 起服务（推荐）")
    parser.add_argument("--opencode-script", default="",
                        help="opencode_supervisor.sh 路径；默认 <root>/scripts/")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    root = Path(args.root).expanduser().resolve() if args.root else Path.cwd()
    worktree = (Path(args.worktree).expanduser().resolve() if args.worktree
                else repo.parent / f".auto-loop-{repo.name}")

    connection = ModelConnection(root / "data/local/llm-connection.json")
    config = connection.load()
    if not all(config.get(key) for key in ("api_key", "base_url", "model")):
        print("未配置模型连接：先在网页保存，或设置 LLM_API_KEY/LLM_BASE_URL/LLM_MODEL")
        return 2

    budget = Budget.tier(args.tier)
    if args.rounds:
        budget.rounds = args.rounds
    isolation = args.isolation
    if isolation == "auto":
        isolation = "clone" if args.engine == "opencode" else "worktree"
    loop = CodingLoop(repo, worktree, shlex.split(args.gate), budget, isolation=isolation)
    if args.engine == "aider":
        worker = AiderAttempt(config, worktree, args.task, binary=args.aider_bin,
                              readonly=args.readonly.split(","))
    elif args.engine == "opencode":
        script = args.opencode_script or str(root / "scripts/opencode_supervisor.sh")
        worker = OpenCodeAttempt(config, worktree, args.task, binary=args.opencode_bin,
                                 port=args.opencode_port, home=args.opencode_home,
                                 readonly=args.readonly.split(","), timeout=420,
                                 supervisor=args.opencode_supervisor,
                                 supervisor_script=script)
    else:
        worker = EditingModel(config, worktree, args.task,
                              readonly=args.readonly.split(","), timeout=180)

    def attempt(context) -> None:
        worker.attempt(context)

    try:
        result = loop.run(attempt)
    except (RuntimeError, OSError) as exc:
        print(f"无法开始：{exc}")
        return 2
    finally:
        closer = getattr(worker, "close", None)
        if callable(closer):
            closer()
        if args.keep:
            print(f"副本保留在：{worktree}")
        else:
            loop.close()

    summary = {
        "status": result.status,
        "rounds": result.rounds,
        "reason": result.reason,
        "green_points": len(result.green_points),
        "model": config.get("model"),
        "engine": args.engine,
        "attempts": [
            {"round": item.round_no, "files": item.files, "lines": item.lines,
             "passed": item.passed, "why": item.output_tail[-160:]}
            for item in result.attempts
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
