"""OpenAPI 契约快照校验。

用法：
    python scripts/openapi_contract.py            # 比对快照，漂移即失败（CI 用）
    python scripts/openapi_contract.py --update   # 契约有意变更后更新快照

退出码：0=契约稳定且三主线响应模型完整；1=漂移、缺快照或主线模型退化。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rag_tech_retriever.api.contract import (
    SNAPSHOT_PATH,
    build_schema,
    canonical,
    diff_snapshots,
    mainline_problems,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenAPI 契约快照校验")
    parser.add_argument("--update", action="store_true", help="用当前应用结构覆盖快照")
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT_PATH, help="快照路径")
    args = parser.parse_args()

    schema = build_schema()
    problems = mainline_problems(schema)
    if problems:
        print("三主线响应契约不完整：")
        for problem in problems:
            print(" -", problem)
        return 1

    if args.update:
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.snapshot.write_text(canonical(schema), encoding="utf-8")
        print(f"已更新快照：{args.snapshot}（paths={len(schema.get('paths', {}))}）")
        return 0

    if not args.snapshot.exists():
        print(f"缺少快照 {args.snapshot}；先运行 --update 并提交快照")
        return 1
    old = json.loads(args.snapshot.read_text(encoding="utf-8"))
    changes = diff_snapshots(old, schema)
    if changes:
        print(f"OpenAPI 漂移 {len(changes)} 处：")
        for change in changes:
            print(" -", change)
        print("如为有意变更，运行 --update 并随代码一起提交快照。")
        return 1
    print(f"OpenAPI 契约稳定：paths={len(schema.get('paths', {}))}，三主线响应模型完整。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
