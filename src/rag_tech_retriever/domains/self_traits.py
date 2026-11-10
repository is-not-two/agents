"""人物特质卡：一条可修订的自我观察，不是固定的人格标签。

设计边界
- 明确区分「观察到的特点」与「对人的判定」：倾向、强度、状态都能改，
  每次保存由 RecordStore 写入版本历史，可以回看自己什么时候改了看法。
- 字段长度上限放宽到可容纳 AES-GCM 密文：开启应用层加密后，
  备份/恢复会对密文再跑一次校验，过窄的上限会误拒绝合法记录。
"""

from rag_tech_retriever.domains.life_planning import DomainError, text

VALENCES = ("待改进", "中性", "优势")
STATUSES = ("观察中", "已改善", "已归档")


def validate_self_trait(payload: dict) -> dict:
    """校验并规范化一张特质卡；拒绝越界枚举与非整数强度。"""
    if not isinstance(payload, dict):
        raise DomainError("人物记录格式错误")

    valence = text(payload.get("valence", ""), "倾向", 16) or VALENCES[0]
    if valence not in VALENCES:
        raise DomainError("倾向只能是待改进 / 中性 / 优势")

    status = text(payload.get("status", ""), "状态", 16) or STATUSES[0]
    if status not in STATUSES:
        raise DomainError("状态只能是观察中 / 已改善 / 已归档")

    intensity = payload.get("intensity", 3)
    if type(intensity) is not int or not 1 <= intensity <= 5:
        raise DomainError("强度必须是 1 到 5 的整数")

    return {
        "title": text(payload.get("title", ""), "特点名称", 2000, True),
        "valence": valence,
        "intensity": intensity,
        "scene": text(payload.get("scene", ""), "常见场景", 4000),
        "note": text(payload.get("note", ""), "观察记录", 20000),
        "status": status,
    }
