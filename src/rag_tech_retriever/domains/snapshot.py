"""跨域备份内容校验与恢复影响预览。"""

import hashlib
import json

from rag_tech_retriever.domains.automation import VALIDATORS
from rag_tech_retriever.domains.jobs import VALIDATORS as JOB_VALIDATORS
from rag_tech_retriever.domains.jobs import validate_references
from rag_tech_retriever.domains.knowledge import validate_knowledge
from rag_tech_retriever.domains.learning import VALIDATORS as LEARNING_VALIDATORS
from rag_tech_retriever.domains.learning import validate_references as validate_learning_references
from rag_tech_retriever.domains.life_planning import DomainError, validate_plan


def validate_snapshot(snapshot: dict) -> dict:
    """进入恢复事务之前验证全部记录，任何非法规划均拒绝整个恢复。"""
    if (
        not isinstance(snapshot, dict)
        or type(snapshot.get("format_version")) is not int
        or snapshot.get("format_version") != 1
    ):
        raise DomainError("不支持的备份格式")
    if not isinstance(snapshot.get("records"), list):
        raise DomainError("备份缺少 records 列表")
    records = []
    ids = set()
    for row in snapshot["records"]:
        validators = {"knowledge": validate_knowledge, "plan": validate_plan, **VALIDATORS, **JOB_VALIDATORS, **LEARNING_VALIDATORS}
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("kind"), str)
            or row.get("kind") not in validators
        ):
            raise DomainError("备份记录类型错误")
        if not isinstance(row.get("id"), str) or not row["id"] or row["id"] in ids:
            raise DomainError("备份记录 ID 缺失或重复")
        if not isinstance(row.get("data"), dict) or not isinstance(row.get("deleted", False), bool):
            raise DomainError("备份正文或删除标志格式错误")
        ids.add(row["id"])
        validate = validators[row["kind"]]
        records.append({**row, "data": validate(row["data"]), "deleted": row.get("deleted", False)})
    validate_references(records)
    validate_learning_references(records)
    return {**snapshot, "records": records}


def snapshot_digest(snapshot: dict) -> str:
    """只比较实际恢复的内容，不将旧阶段或导出历史当作待写入记录。"""
    content = json.dumps(
        snapshot["records"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(content.encode()).hexdigest()


def preview_restore(current: dict, target: dict) -> dict:
    """逐记录对齐持久化恢复语义，预览不会修改工作区。"""
    before = {r["id"]: r for r in current["records"]}
    desired = {r["id"]: r for r in target["records"]}
    counts = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}
    kinds: dict[str, int] = {}
    changes = []
    for record_id in sorted(before.keys() | desired.keys()):
        old, new = before.get(record_id), desired.get(record_id)
        if old and new and old["kind"] != new["kind"]:
            raise DomainError("备份中的记录类型与当前同名 ID 不一致，无法恢复")
        if new is None:
            action = "unchanged" if old["deleted"] else "removed"
        elif old is None:
            action = "added"
        elif old["data"] == new["data"] and old["deleted"] == new["deleted"]:
            action = "unchanged"
        else:
            action = "updated"
        counts[action] += 1
        row = new or old
        if action != "unchanged":
            changes.append(
                {
                    "id": record_id,
                    "kind": row["kind"],
                    "title": row["data"]["title"],
                    "action": action,
                    "to_trash": new is None or new["deleted"],
                }
            )
    for row in target["records"]:
        if not row["deleted"]:
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    return {
        "counts": counts,
        "backup_counts": kinds,
        "changes": changes[:50],
        "change_count": len(changes),
        "trash_count": sum(r["deleted"] for r in target["records"]),
    }
