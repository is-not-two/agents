"""确认建卡与原子复习：沿用 PostgreSQL 版本审计和 CAS。"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from uuid import uuid4

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.jobs import strings
from rag_tech_retriever.domains.learning import next_schedule, validate_card, validate_review
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.record_store import RecordMissing, RecordStore, VersionConflict


def utcnow() -> str:
    """统一 UTC 时间，不依赖浏览器时钟提交调度结果。"""
    return datetime.now(timezone.utc).isoformat()


class LearningService:
    """来源候选必须人工确认；评分、卡片进度和审计同一事务。"""

    def __init__(self, store: RecordStore) -> None:
        self.store = store
        self.policy = ConfigLoader(store.config.settings_path.parent / "learning.yaml").get("learning", {})
        for key in ("first_days", "second_days", "ease_changes"):
            values = self.policy.get(key)
            if not isinstance(values, list) or len(values) != 4 or any(type(v) not in {int, float} or not math.isfinite(v) for v in values):
                raise DomainError("复习调度配置无效：" + key)
        if any(type(v) is not int or not 1 <= v <= 365 for key in ("first_days", "second_days") for v in self.policy[key]):
            raise DomainError("复习间隔配置必须为 1–365 天的整数")
        for key in ("min_ease", "max_ease", "difficult_multiplier"):
            value = self.policy.get(key)
            if type(value) not in {int, float} or not math.isfinite(value) or not 1 <= value <= 3:
                raise DomainError("复习难度配置无效：" + key)
        if not 1.3 <= self.policy["min_ease"] <= self.policy["max_ease"] <= 3 or type(self.policy.get("max_interval_days")) is not int or not 1 <= self.policy["max_interval_days"] <= 365:
            raise DomainError("复习调度上下限配置无效")

    def _card(self, cur, card_id: str, deleted: bool = False) -> dict:
        cur.execute(f"SELECT * FROM {self.store.records} WHERE id=%s FOR UPDATE", (card_id,))
        row = cur.fetchone()
        if row is None or row["kind"] != "learning_card" or (row["deleted"] and not deleted):
            raise RecordMissing("复习卡不存在或已归档")
        return row

    def save(self, payload: dict, card_id: str | None = None, version: int | None = None) -> dict:
        """只开放正文、暂停与人工改期；来源、次数和难度由服务控制。"""
        editable = {"title", "answer_ref", "due_at", "paused"}
        if set(payload) - editable:
            raise DomainError("不能在普通编辑中修改来源或复习进度")
        with self.store.transaction() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.store.prefix + ":learning",))
            old = self._card(cur, card_id) if card_id else None
            if old and old["version"] != version:
                raise VersionConflict("复习卡已更新，本次输入未覆盖原记录")
            data = validate_card({**(old["data"] if old else {"due_at": utcnow()}), **payload})
            return self.store._save(cur, "learning_card", data, card_id or uuid4().hex, version)

    def from_interview(self, report_id: str, version: int, points: list, confirmation: str) -> dict:
        """仅将当前复盘中选中的薄弱点建卡；重复确认不会新建副本。"""
        if confirmation != "确认创建复习卡":
            raise DomainError("请明确确认创建复习卡")
        points = strings(points, "选中薄弱点")
        if not points:
            raise DomainError("请选择至少一条薄弱点")
        with self.store.transaction() as cur:
            for key in (":jobs", ":learning"):
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.store.prefix + key,))
            cur.execute(f"SELECT * FROM {self.store.records} WHERE id=%s FOR UPDATE", (report_id,))
            report = cur.fetchone()
            if report is None or report["kind"] != "interview_report" or report["deleted"]:
                raise RecordMissing("面试复盘不存在或已归档")
            if report["version"] != version:
                raise VersionConflict("面试复盘已变化，请重新读取候选")
            if not set(points) <= set(report["data"]["weak_points"]):
                raise DomainError("只能选择本次复盘已有的薄弱点")
            created, reused = [], []
            for point in points:
                key = hashlib.sha256((report_id + "\n" + point).encode()).hexdigest()
                record_id = "learn-" + key
                cur.execute(f"SELECT * FROM {self.store.records} WHERE id=%s", (record_id,))
                old = cur.fetchone()
                if old:
                    if old["kind"] != "learning_card" or old["deleted"]:
                        raise VersionConflict("对应复习卡已归档，请到回收站显式恢复")
                    reused.append(self.store._serialize(old))
                    continue
                data = validate_card({"title": point, "answer_ref": "来源：" + report["data"]["title"],
                                      "source": "interview", "source_id": report_id, "source_version": version,
                                      "source_key": key, "due_at": utcnow()})
                created.append(self.store._save(cur, "learning_card", data, record_id, None))
            return {"created": created, "reused": reused}

    def review(self, card_id: str, version: int, rating: int, request_id: str) -> dict:
        """同一请求可安全重放；变更载荷或过期版本不会再次推进间隔。"""
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{16,100}", request_id):
            raise DomainError("复习操作必须携带 16–100 位稳定请求标识")
        if type(rating) is not int or not 0 <= rating <= 3:
            raise DomainError("复习自评必须为 0–3")
        review_id = "review-" + hashlib.sha256((card_id + "/" + request_id).encode()).hexdigest()
        with self.store.transaction() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.store.prefix + ":learning",))
            card = self._card(cur, card_id)
            cur.execute(f"SELECT * FROM {self.store.records} WHERE id=%s", (review_id,))
            previous = cur.fetchone()
            if previous:
                if previous["kind"] != "learning_review" or previous["data"]["rating"] != rating or previous["data"]["card_version"] != version:
                    raise VersionConflict("同一复习操作标识不能用于不同评分或版本")
                return {"card": self.store._serialize(card), "review": self.store._serialize(previous), "replayed": True}
            if card["version"] != version:
                raise VersionConflict("复习卡已更新，请读取最新内容后自评")
            now = utcnow()
            if card["data"]["paused"] or card["data"]["due_at"] > now:
                raise VersionConflict("此卡片已暂停或尚未到期，未重复记录复习")
            updated = next_schedule(card["data"], rating, now, self.policy)
            saved = self.store._save(cur, "learning_card", updated, card_id, version)
            record = validate_review({"title": "复习：" + card["data"]["title"], "card_id": card_id,
                                      "rating": rating, "card_version": version, "request_id": request_id,
                                      "reviewed_at": now, "previous_due_at": card["data"]["due_at"], "next_due_at": updated["due_at"]})
            audit = self.store._save(cur, "learning_review", record, review_id, None)
            return {"card": saved, "review": audit, "replayed": False}

    def from_jd(self, lead_id: str, version: int, profile_revision: str, names: list, confirmation: str, insights) -> dict:
        """只把当前对照中的缺证据项作为人工确认学习候选，不认定不会。"""
        if confirmation != "确认创建复习卡":
            raise DomainError("请明确确认创建复习卡")
        names = strings(names, "选中要求")
        if not names:
            raise DomainError("请选择至少一项学习候选")
        gap = insights.gap(lead_id)
        if gap["stale"] or gap["lead_version"] != version or gap["profile_revision"] != profile_revision:
            raise VersionConflict("岗位、资料或分析已变化，请重新核对候选")
        eligible = {r["name"]: r for r in gap["analysis"]["requirements"] if r["assessment"] != "evidence_supplied" and r["priority"] != "not_required"}
        if not set(names) <= eligible.keys():
            raise DomainError("候选必须来自当前分析中未提供充分证据的要求")
        with self.store.transaction() as cur:
            for key in (":jobs", ":learning"):
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.store.prefix + key,))
            cur.execute(f"SELECT * FROM {self.store.records} WHERE id=%s FOR UPDATE", (lead_id,))
            lead = cur.fetchone()
            if lead is None or lead["kind"] != "job_lead" or lead["deleted"]:
                raise RecordMissing("岗位不存在")
            if lead["version"] != version or insights.profile()["revision"] != profile_revision:
                raise VersionConflict("确认期间资料变化，未保存过期候选")
            created, reused = [], []
            for name in names:
                key = hashlib.sha256(("jd:" + lead_id + ":" + name.casefold()).encode()).hexdigest()
                record_id = "learn-jd-" + key
                cur.execute(f"SELECT * FROM {self.store.records} WHERE id=%s", (record_id,))
                old = cur.fetchone()
                if old:
                    if old["kind"] != "learning_card" or old["deleted"]:
                        raise VersionConflict("对应学习卡已归档，请显式恢复")
                    reused.append(self.store._serialize(old)); continue
                data = validate_card({"title": "复习：" + name, "answer_ref": "岗位原文要求（不是答案）：" + eligible[name]["quote"] + "\n请补充经过查证的学习资料和项目证据。",
                                      "source": "jd_gap", "source_id": lead_id, "source_version": version,
                                      "source_key": key, "due_at": utcnow()})
                created.append(self.store._save(cur, "learning_card", data, record_id, None))
            return {"created": created, "reused": reused}

    def overview(self, trash: bool = False) -> dict:
        """到期列表与完整卡片采用同一数据库快照，不隐式创建或修改卡片。"""
        with self.store.transaction() as cur:
            cur.execute(f"SELECT * FROM {self.store.records} WHERE kind='learning_card' AND deleted=%s ORDER BY data->>'due_at',id", (trash,))
            cards = [self.store._serialize(row) for row in cur.fetchall()]
        now = utcnow()
        due = [row["id"] for row in cards if not row["data"]["paused"] and row["data"]["due_at"] <= now]
        return {"cards": cards, "due_ids": due, "as_of": now}

    def history(self, card_id: str) -> list:
        """只读复习证据；与内容的版本历史分开，不开放审计修改接口。"""
        with self.store.transaction() as cur:
            self._card(cur, card_id, deleted=True)
            cur.execute(f"SELECT * FROM {self.store.records} WHERE kind='learning_review' AND data->>'card_id'=%s ORDER BY created_at DESC,id LIMIT 100", (card_id,))
            return [self.store._serialize(row) for row in cur.fetchall()]
