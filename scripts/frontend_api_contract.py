"""前端接口契约检查：shilie 前端引用的每个 /api 路径都必须在 OpenAPI 中存在。

只做静态比对，不连数据库、不启动服务，可在本地与发布门禁中快速执行。
路径比较按“形状”归一化：`${id}` / `{record_id}` 都折叠为 `{}`，忽略查询串。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SPEC = PROJECT / "docs" / "openapi.json"
FRONTEND = PROJECT / "shilie" / "src"

CALL_API = re.compile(r"""api\(\s*(["'`])([^"'`\n]+)\1""")
CALL_VUE = re.compile(r"""\b(?:request|requestText|send)(?:<[^\n]*?>)?\(\s*(["'`])([^"'`\n]+)\1""")
CALL_FETCH = re.compile(r"""fetch\(\s*(["'`])(/api/[^"'`\n]*)\1""")
PARAM = re.compile(r"\{[^}]*\}")
TEMPLATE = re.compile(r"\$\{[^}]*\}")


def shape(path: str) -> str:
    """把参数段归一化，便于比较前后端的路径形状。"""
    path = path.split("?")[0]
    path = TEMPLATE.sub("{}", path)
    return PARAM.sub("{}", path)


def segments(path: str) -> list[str]:
    return [part for part in shape(path).split("/") if part]


def matches(call: str, spec_path: str, prefix: bool = False) -> bool:
    """按段比较；参数段可匹配任意值；prefix=True 允许前端路径是更长端点的一段前缀。"""
    left, right = segments(call), segments(spec_path)
    if prefix:
        if len(right) < len(left):
            return False
    elif len(left) != len(right):
        return False
    for call_part, spec_part in zip(left, right):
        if call_part == "{}" or spec_part == "{}":
            continue
        if call_part != spec_part:
            return False
    return True


def extract_calls(text: str, api_base: str = "/api/") -> set[str]:
    """从一段 JS 源码提取 /api 引用；支持跨行调用与字符串拼接出的前缀。

    api_base: 该文件里 api("x") helper 的实际前缀。工作台是 "/api/"；
    社区前端 src/community/api.ts 的 helper 拼 "/api/community/" + path，
    其调用（如 api("posts")）应映射到 /api/community/posts。
    """
    calls: set[str] = set()
    for pattern in (CALL_API, CALL_VUE):
        for match in pattern.finditer(text):
            calls.add(api_base + match.group(2).lstrip("/"))
    for match in CALL_FETCH.finditer(text):
        calls.add(match.group(2))
    # helper 自身的 base 拼接（如 fetch("/api/community/"+path)）是模板而非具体接口
    calls.discard(api_base.rstrip("/") + "/")
    calls.discard("/api/")
    return calls


def main() -> int:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    paths = spec["paths"]
    calls: set[str] = set()
    for file in FRONTEND.rglob("*"):
        if file.suffix in {".ts", ".vue"} and file.name != "demo-data.ts":
            # 社区前端的 api() helper 拼 "/api/community/" + path；
            # 工作台的 api() helper 拼 "/api/" + path。按目录选 base。
            parts = file.relative_to(FRONTEND).parts
            base = "/api/community/" if "community" in parts else "/api/"
            calls |= extract_calls(file.read_text(encoding="utf-8"), api_base=base)
    if not calls:
        print("未发现 Vue 前端 API 引用")
        return 1
    missing = []
    for url in sorted(calls):
        if url.endswith("/"):
            # 动态拼接（如 api("private/wish/" + id)）：按前缀段比较，允许参数段匹配字面量
            if any(matches(url, path, prefix=True) for path in paths):
                continue
        elif any(matches(url, path) for path in paths):
            continue
        missing.append(url)
    print(f"前端 /api 引用 {len(calls)} 条，OpenAPI {len(paths)} 条路径")
    if missing:
        print("以下前端引用在 OpenAPI 中没有对应路径：")
        for url in missing:
            print("  -", url)
        return 1
    print("前端接口引用与 OpenAPI 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
