"""网页录入的个人知识条目校验。"""

import re

from rag_tech_retriever.domains.life_planning import DomainError, text

_TAG_SPLIT = re.compile(r"[,，、]")


def normalize_tags(raw: list) -> list[str]:
    """标签规范化（LEARN-001）：按英文/中文逗号、顿号拆分，去两端空白，
    丢弃空项，重复项保留首次出现顺序。单个标签长度与总数上限由调用方校验。
    """
    items: list[str] = []
    for entry in raw:
        if not isinstance(entry, str):
            raise DomainError("标签必须是字符串")
        items.extend(piece.strip() for piece in _TAG_SPLIT.split(entry))
    return list(dict.fromkeys(item for item in items if item))


def validate_knowledge(payload: dict) -> dict:
    """内容、标签与来源校验；原始技术语料另行只读管理。"""
    tags = payload.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 15:
        raise DomainError("标签必须是列表，最多 15 个")
    tags = normalize_tags(tags)
    if len(tags) > 15:
        raise DomainError("拆分后标签最多 15 个")
    return {
        "title": text(payload.get("title", ""), "知识标题", 160, True),
        "content": text(payload.get("content", ""), "知识正文", 100000, True),
        "tags": [text(tag, "标签", 40, True) for tag in tags],
        "source": text(payload.get("source", ""), "来源", 1000),
    }
