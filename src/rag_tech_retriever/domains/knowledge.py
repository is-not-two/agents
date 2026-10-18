"""网页录入的个人知识条目校验。"""

from rag_tech_retriever.domains.life_planning import DomainError, text


def validate_knowledge(payload: dict) -> dict:
    """内容、标签与来源校验；原始技术语料另行只读管理。"""
    tags = payload.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 15:
        raise DomainError("标签必须是列表，最多 15 个")
    return {
        "title": text(payload.get("title", ""), "知识标题", 160, True),
        "content": text(payload.get("content", ""), "知识正文", 100000, True),
        "tags": list(dict.fromkeys(text(tag, "标签", 40, True) for tag in tags)),
        "source": text(payload.get("source", ""), "来源", 1000),
    }
