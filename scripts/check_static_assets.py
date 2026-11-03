"""静态资源引用检查：页面与 CSS 引用的本地文件必须真实存在。

覆盖两类引用：
- `index.html` 里以 `/static/` 开头的 src/href；
- 前端 CSS 里的 `url(...)`（相对 CSS 所在目录，忽略 data:/http(s) 与归档目录）。

不启动服务、不连数据库，用于在发布前拦住“改名后忘记改引用”导致的 404 背景图/脚本。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
STATIC = PROJECT / "src" / "rag_tech_retriever" / "api" / "static"
SHILIE = STATIC / "shilie"

HTML_REF = re.compile(r"""<(?:script|link|img)[^>]+(?:src|href)="([^"]+)\"""")
CSS_URL = re.compile(r"""url\((['"]?)([^)'"]+)\1\)""")


def _exists_file(base: Path, raw: str) -> bool:
    """去掉查询串后检查文件是否存在（URL 解码不涉及本项目的静态名）。"""
    target = raw.split("?")[0].split("#")[0]
    if not target or target.startswith(("data:", "http://", "https://", "#")):
        return True
    return (base / target.lstrip("/")).is_file()


def missing_html_refs() -> list[str]:
    """index.html 中 /static/ 引用缺失列表。"""
    html = (SHILIE / "index.html").read_text(encoding="utf-8")
    missing = []
    for url in HTML_REF.findall(html):
        if not url.startswith("/static/"):
            continue
        if not _exists_file(STATIC, url[len("/static/"):]):
            missing.append(url)
    return missing


def missing_css_urls() -> list[str]:
    """前端 CSS（不含 _archived）里 url() 缺失列表。"""
    missing = []
    for css in SHILIE.glob("*.css"):
        for _, raw in CSS_URL.findall(css.read_text(encoding="utf-8")):
            if raw.startswith(("data:", "http://", "https://", "#")):
                continue
            if not (SHILIE / raw.split("?")[0].split("#")[0]).is_file():
                missing.append(f"{css.name}: {raw}")
    return missing


def main() -> int:
    problems = missing_html_refs() + missing_css_urls()
    if problems:
        print("静态资源引用缺失：")
        for item in problems:
            print("  -", item)
        return 1
    print("静态资源引用完整（index.html + CSS）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
