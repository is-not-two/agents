"""求职服务：单事务引用/状态校验、乐观锁、关联归档保护。"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.jobs import TRANSITIONS, VALIDATORS, funnel_stages
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.record_store import RecordMissing, RecordStore, VersionConflict


class JobsService:
    """复用当前表及版本表；业务锁只串行化求职写入，不锁全站。"""

    def __init__(self, store: RecordStore, config: ConfigLoader | None = None) -> None:
        self.store = store
        # 路由传入应用配置；直接实例化（测试替身/脚本）时回退到存储配置或默认配置目录。
        source = config or getattr(store, "config", None) or ConfigLoader.load_default()
        root = source.settings_path.parent
        funnel = ConfigLoader(root / "jobs.yaml").get("jobs.funnel", {}) if (root / "jobs.yaml").exists() else {}
        target = funnel.get("weekly_application_target", 5) if isinstance(funnel, dict) else 5
        if type(target) is not int or not 1 <= target <= 100:
            raise DomainError("求职漏斗的每周投递目标配置无效")
        self.weekly_target = target
        offset = ConfigLoader(root / "notifications.yaml").get(
            "notifications.timezone_offset_minutes", 480
        ) if (root / "notifications.yaml").exists() else 480
        if type(offset) is not int or not -720 <= offset <= 840:
            raise DomainError("求职漏斗时区配置无效")
        self.tz = timezone(timedelta(minutes=offset))

    def _week_window(self, now: datetime) -> tuple[str, str]:
        """周窗口按配置时区的周一起算，统一转 UTC 后用于字符串比较。"""
        local = now.astimezone(self.tz)
        monday = local.date() - timedelta(days=local.weekday())
        start = datetime.combine(monday, time(), self.tz).astimezone(timezone.utc)
        return start.isoformat(), (start + timedelta(days=7)).isoformat()

    def _row(self, cur, record_id: str, kind: str | None = None, deleted: bool = False) -> dict:
        cur.execute(f"SELECT * FROM {self.store.records} WHERE id=%s FOR UPDATE", (record_id,))
        row = cur.fetchone()
        if row is None or (kind is not None and row["kind"] != kind) or (row["deleted"] and not deleted):
            raise RecordMissing("求职关联记录不存在或已归档")
        return row

    def _prepare(self, cur, kind: str, payload: dict, old: dict | None, restoring: bool = False) -> dict:
        data = VALIDATORS[kind](payload)
        if kind == "application":
            parent = self._row(cur, data["lead_id"], "job_lead")
            if data["resume_version_id"]:
                self._row(cur, data["resume_version_id"], "resume_version")
            if old and data["lead_id"] != old["data"]["lead_id"]:
                raise DomainError("投递所属岗位不能更改，请为新岗位新建投递")
            previous = old["data"]["status"] if old else "collected"
            if not restoring and data["status"] != previous and data["status"] not in TRANSITIONS[previous]:
                raise DomainError("不支持此状态跳转；请按收藏、投递、跟进/面试、结果推进")
            if data["status"] != "collected" and not data["applied_at"] and (previous != "collected" or data["status"] != "rejected"):
                data["applied_at"] = (old["data"].get("applied_at") if old else "") or datetime.now(timezone.utc).isoformat()
            data["title"] = parent["data"]["company"] + " / " + parent["data"]["title"]
        elif kind == "interview_report":
            parent = self._row(cur, data["application_id"], "application")
            if old and data["application_id"] != old["data"]["application_id"]:
                raise DomainError("复盘所属投递不能更改")
            if not restoring and parent["data"]["status"] not in {"interviewing", "offered", "rejected"}:
                raise DomainError("请先将投递推进到面试中，再记录面试复盘")
            data["title"] = parent["data"]["title"] + f" / 第 {data['round']} 轮复盘"
            data["interviewed_at"] = data["interviewed_at"] or datetime.now(timezone.utc).isoformat()
        return data

    def save(self, kind: str, payload: dict, record_id: str | None = None, version: int | None = None, patch: bool = False) -> dict:
        """校验与写入同一事务；旧版本、跨类型和已归档编辑均拒绝。"""
        from uuid import uuid4

        if kind not in VALIDATORS:
            raise DomainError("不支持的求职记录类型")
        with self.store.transaction() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.store.prefix + ":jobs",))
            old = self._row(cur, record_id, kind) if record_id else None
            if old and version != old["version"]:
                raise VersionConflict("求职记录已更新，请刷新后重试；本次输入未覆盖已有内容")
            data = self._prepare(cur, kind, {**old["data"], **payload} if old and patch else payload, old)
            if kind == "application" and old is None:
                cur.execute(f"SELECT id FROM {self.store.records} WHERE kind='application' AND deleted=FALSE AND data->>'lead_id'=%s LIMIT 1", (data["lead_id"],))
                if cur.fetchone():
                    raise VersionConflict("此岗位已有投递记录，请编辑现有记录，避免重复录入")
            return self.store._save(cur, kind, data, record_id or uuid4().hex, version)

    def archive(self, record_id: str, version: int) -> dict:
        """阻止归档仍被有效求职记录引用的父项；子项需先独立归档。"""
        with self.store.transaction() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.store.prefix + ":jobs",))
            row = self._row(cur, record_id)
            if row["kind"] not in VALIDATORS:
                raise RecordMissing("求职记录不存在")
            field = {"job_lead": "lead_id", "application": "application_id", "resume_version": "resume_version_id"}.get(row["kind"])
            if field:
                cur.execute(f"SELECT id FROM {self.store.records} WHERE deleted=FALSE AND data->>%s=%s LIMIT 1", (field, record_id))
                if cur.fetchone():
                    raise VersionConflict("该记录仍有关联投递或面试复盘，请先归档子记录")
            return self.store._save(cur, row["kind"], row["data"], record_id, version, "delete", True)

    def restore(self, record_id: str, target_version: int, current_version: int) -> dict:
        """显式历史恢复保留审计；父项归档时拒绝恢复孤立子项。"""
        with self.store.transaction() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.store.prefix + ":jobs",))
            row = self._row(cur, record_id, deleted=True)
            if row["kind"] not in VALIDATORS:
                raise RecordMissing("求职记录不存在")
            if row["version"] != current_version:
                raise VersionConflict("求职记录已更新，请重新读取历史")
            cur.execute(f"SELECT data FROM {self.store.versions} WHERE record_id=%s AND version=%s", (record_id, target_version))
            target = cur.fetchone()
            if target is None:
                raise RecordMissing("历史版本不存在")
            data = self._prepare(cur, row["kind"],
                                 self.store._open(row["kind"], target["data"]), row, restoring=True)
            return self.store._save(cur, row["kind"], data, record_id, current_version, f"restore:v{target_version}")

    def overview(self, trash: bool = False) -> dict:
        """一次读取得到一致列表，日期在 UTC 比较，关闭的投递不算待跟进。"""
        with self.store.transaction() as cur:
            cur.execute(f"SELECT * FROM {self.store.records} WHERE kind=ANY(%s) AND deleted=%s ORDER BY updated_at DESC,id", (sorted(VALIDATORS), trash))
            rows = [self.store._serialize(row) for row in cur.fetchall()]
        grouped = {kind: [row for row in rows if row["kind"] == kind] for kind in VALIDATORS}
        now = datetime.now(timezone.utc).isoformat()
        applications = grouped["application"]
        due = [row["id"] for row in applications if row["data"]["follow_up_at"] and row["data"]["follow_up_at"] <= now and row["data"]["status"] not in {"offered", "rejected"}]
        funnel = None
        if not trash:
            week_start, week_end = self._week_window(datetime.now(timezone.utc))
            funnel = funnel_stages(
                grouped["job_lead"], applications, grouped["interview_report"],
                now=now, week_start=week_start, week_end=week_end, target=self.weekly_target,
            )
        return {**grouped, "due_application_ids": due, "as_of": now, "funnel": funnel,
                "counts": {status: sum(row["data"]["status"] == status for row in applications) for status in TRANSITIONS}}
