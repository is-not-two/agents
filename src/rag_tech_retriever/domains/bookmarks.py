"""网页收藏校验：只接受 http/https 外链，分类与标签做长度约束。

收藏是“可点击跳转”的独立条目，不与知识笔记共用字段语义：
``url`` 是外链本身，``note`` 是可选的摘录/备注，正文不参与全文检索。
"""

from urllib.parse import urlsplit

from rag_tech_retriever.domains.knowledge import normalize_tags
from rag_tech_retriever.domains.life_planning import DomainError, text

DEFAULT_CATEGORY = "未分类"
_ALLOWED_SCHEMES = {"http", "https"}


def validate_bookmark(payload: dict) -> dict:
    """校验并规范化收藏条目；拒绝脚本、内嵌数据与相对链接。"""
    url = text(payload.get("url", ""), "收藏网址", 2048, True)
    if any(char.isspace() for char in url):
        raise DomainError("收藏网址不能包含空白字符")
    parts = urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES or not parts.netloc:
        raise DomainError("收藏网址必须是完整的 http/https 链接")
    if parts.username or parts.password:
        raise DomainError("收藏网址不能包含账号密码")

    tags = payload.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 10:
        raise DomainError("标签必须是列表，最多 10 个")
    tags = normalize_tags(tags)
    if len(tags) > 10:
        raise DomainError("拆分后标签最多 10 个")

    return {
        "title": text(payload.get("title", ""), "收藏标题", 160, True),
        "url": url,
        "category": text(payload.get("category", ""), "分类", 24) or DEFAULT_CATEGORY,
        "tags": [text(tag, "标签", 24, True) for tag in tags],
        "note": text(payload.get("note", ""), "备注", 2000),
    }
