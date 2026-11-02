"""谨记名单（个人错题/教训）领域校验：类型分类 + 必填简述 + 选填经过与对策。

预设类型：技术 / 操作 / 判断 / 习惯 / 其他；也允许 ≤20 字的自定义类型，
前端下拉提供预设，域层只做非空与长度约束。
"""

from rag_tech_retriever.domains.life_planning import DomainError, text

LESSON_CATEGORIES = ("技术", "操作", "判断", "习惯", "其他")


def validate_lesson(payload: dict) -> dict:
    category = payload.get("category", "其他")
    if not isinstance(category, str):
        raise DomainError("错误类型必须是字符串")
    cleaned = category.strip()
    if not cleaned or len(cleaned) > 20:
        raise DomainError("错误类型必须非空且不超过 20 字")
    return {
        "title": text(payload.get("title", ""), "错误简述", 160, True),
        "category": cleaned,
        "content": text(payload.get("content", ""), "经过与原因", 20000),
        "remedy": text(payload.get("remedy", ""), "对策", 2000),
    }
