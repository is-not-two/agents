"""静态资源版本一致性检查。

背景：shilie 前端的缓存失效靠 ?v=N 查询参数，index.html 引用与各 JS 模块
import 说明符里的版本必须一致；历史上版本号分裂（v15/v22/v23/v24）曾导致
"改了没反应"被误判为代码错误。本脚本只读校验，不做任何修改。

用法：python scripts/check_static_version.py
退出码：0=全部一致；1=发现不一致或缺失版本（输出明细）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "rag_tech_retriever" / "api" / "static" / "shilie"
VERSION_RE = re.compile(r"\?v=(\d+)")


def collect() -> list[tuple[str, str, int]]:
    """返回 (文件, 上下文, 版本号) 列表，覆盖 index.html 与全部 JS 模块。"""
    found: list[tuple[str, str, int]] = []
    targets = [STATIC / "index.html", *sorted(STATIC.glob("*.js"))]
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in VERSION_RE.finditer(text):
            context = text[max(0, match.start() - 60) : match.end() + 20].replace("\n", " ")
            found.append((path.name, context.strip(), int(match.group(1))))
    return found


def main() -> int:
    refs = collect()
    if not refs:
        print("失败：未找到任何 ?v= 版本引用（检查目录或写法是否变更）")
        return 1
    versions = sorted({v for _, _, v in refs})
    count_by_file = {name: sum(1 for f, _, _ in refs if f == name) for name in {f for f, _, _ in refs}}
    print(f"共 {len(refs)} 处版本引用，分布：")
    for name, count in sorted(count_by_file.items()):
        print(f"  {name}: {count} 处")
    if len(versions) == 1:
        print(f"通过：全部为 v{versions[0]}")
        return 0
    print(f"失败：版本分裂 {['v' + str(v) for v in versions]}，明细：")
    for name, context, version in refs:
        if version != versions[-1]:
            print(f"  {name} (v{version}): ...{context}...")
    return 1


if __name__ == "__main__":
    sys.exit(main())
