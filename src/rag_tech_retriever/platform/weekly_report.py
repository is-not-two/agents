"""周报统计：事件时间窗口、分组口径、纯统计降级与冻结留档。"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.job_analysis import JobInsights, request_json
from rag_tech_retriever.platform.mcp_client import ToolError
from rag_tech_retriever.platform.model_connection import ModelConnection
from rag_tech_retriever.platform.private_json import PrivateJson
from rag_tech_retriever.platform.record_store import RecordStore, StorageError


class WeeklyReport:
    """快照是生成时刻事实，不把今天的状态标成历史周末状态。"""

    def __init__(self, root: Path, store: RecordStore, connection: ModelConnection) -> None:
        self.root, self.store, self.connection = root, store, connection
        offset = ConfigLoader(store.config.settings_path.parent / "notifications.yaml").get(
            "notifications.timezone_offset_minutes"
        )
        if type(offset) is not int or not -720 <= offset <= 840:
            raise DomainError("周报时区配置无效")
        self.tz = timezone(timedelta(minutes=offset))
        self.insights = JobInsights(root, store, connection)

    def report(self, day: str = "", now: datetime | None = None, *, read_limits: dict | None = None) -> dict:
        """查询不调用模型、不写文件；空分母的进面率是 null 而不是 0%。"""
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            selected = date.fromisoformat(day) if day else now.astimezone(self.tz).date()
        except (TypeError, ValueError) as exc:
            raise DomainError("请选择有效周报日期 YYYY-MM-DD") from exc
        monday = selected - timedelta(days=selected.weekday())
        start = datetime.combine(monday, time(), self.tz).astimezone(timezone.utc)
        end = start + timedelta(days=7)
        with self.store.transaction() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            if read_limits is not None:
                if (set(read_limits) != {"max_records", "max_versions", "statement_timeout_ms"}
                        or any(type(v) is not int or not 1 <= v <= 100000 for v in read_limits.values())):
                    raise DomainError("只读统计限额无效")
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(f"SET LOCAL statement_timeout = {read_limits['statement_timeout_ms']}")
            records_limit = f" LIMIT {read_limits['max_records'] + 1}" if read_limits is not None else ""
            cur.execute(
                f"SELECT * FROM {self.store.records} WHERE deleted=FALSE AND kind=ANY(%s) ORDER BY id" + records_limit,
                (
                    [
                        "job_lead",
                        "application",
                        "interview_report",
                        "learning_card",
                        "learning_review",
                        "knowledge",
                        "plan",
                    ],
                ),
            )
            rows = [self.store._serialize(row) for row in cur.fetchall()]
            if read_limits is not None and len(rows) > read_limits["max_records"]:
                raise DomainError("统计数据超过服务器上限，未返回截断的虚假统计")
            plans = [row["id"] for row in rows if row["kind"] == "plan"]
            versions_limit = f" LIMIT {read_limits['max_versions'] + 1}" if read_limits is not None else ""
            cur.execute(
                f"SELECT v.record_id,v.version,v.data,v.deleted,v.created_at,r.kind FROM {self.store.versions} v "
                "JOIN " + self.store.records + " r ON r.id=v.record_id "
                "WHERE v.record_id=ANY(%s) AND v.created_at<%s AND v.created_at<=%s "
                "ORDER BY v.record_id,v.version" + versions_limit,
                (plans, end, now),
            )
            versions = cur.fetchall()
            if read_limits is not None and len(versions) > read_limits["max_versions"]:
                raise DomainError("统计版本超过服务器上限，未返回截断的虚假统计")

        def inside(value: str) -> bool:
            return (
                bool(value)
                and start <= datetime.fromisoformat(value.replace("Z", "+00:00")) < end
                and datetime.fromisoformat(value.replace("Z", "+00:00")) <= now
            )

        applications = [row for row in rows if row["kind"] == "application"]
        cohort = [row for row in applications if inside(row["data"]["applied_at"])]
        reports = [row for row in rows if row["kind"] == "interview_report"]
        weekly_interviews = [row for row in reports if inside(row["data"]["interviewed_at"])]
        interviewed = {
            row["data"]["application_id"]
            for row in reports
            if row["data"]["interviewed_at"] and row["data"]["interviewed_at"] <= now.isoformat()
        }
        cohort_interviewed = sum(row["id"] in interviewed for row in cohort)
        questions = Counter(
            q for row in weekly_interviews for q in {q["q"] for q in row["data"]["questions"]}
        )
        weak = Counter(
            point for row in weekly_interviews for point in set(row["data"]["weak_points"])
        )
        previous, completed = {}, 0
        for version in versions:
            current = (
                {
                    node["id"]
                    for act in version["data"]["acts"]
                    for node in act["nodes"]
                    if node["done"]
                }
                if not version["deleted"]
                else set()
            )
            old = previous.get(version["record_id"], set())
            if start <= version["created_at"] < end and version["version"] > 1:
                completed += len(current - old)
            previous[version["record_id"]] = current
        due_cards = [
            row
            for row in rows
            if row["kind"] == "learning_card"
            and not row["data"]["paused"]
            and row["data"]["due_at"] <= now.isoformat()
        ]
        due_followups = [
            row
            for row in applications
            if row["data"]["status"] not in {"offered", "rejected"}
            and row["data"]["follow_up_at"]
            and row["data"]["follow_up_at"] <= now.isoformat()
        ]
        metrics = {
            "applications_submitted": len(cohort),
            "interviews_recorded": len(weekly_interviews),
            "cohort_interviewed": cohort_interviewed,
            "cohort_interview_rate": round(cohort_interviewed / len(cohort), 4) if cohort else None,
            "reviews_recorded": sum(
                row["kind"] == "learning_review" and inside(row["data"]["reviewed_at"])
                for row in rows
            ),
            "knowledge_added": sum(
                row["kind"] == "knowledge" and inside(row["created_at"]) for row in rows
            ),
            "plan_completion_events": completed,
            "followups_due": len(due_followups),
            "reviews_due": len(due_cards),
        }
        fingerprint = PrivateJson.revision(
            {
                "records": [{"id": row["id"], "version": row["version"]} for row in rows],
                "week": monday.isoformat(),
                "metrics": metrics,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "policy": self.insights.policy_revision,
                "code": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            }
        )
        return {
            "schema": 1,
            "week_start": monday.isoformat(),
            "week_end_exclusive": (monday + timedelta(days=7)).isoformat(),
            "window_start_utc": start.isoformat(),
            "window_end_utc": end.isoformat(),
            "as_of": now.isoformat(),
            "metrics": metrics,
            "pipeline_current": dict(Counter(row["data"]["status"] for row in applications)),
            "cohort_current": dict(Counter(row["data"]["status"] for row in cohort)),
            "top_questions": [{"question": q, "count": n} for q, n in questions.most_common(5)],
            "top_weak_points": [{"point": p, "count": n} for p, n in weak.most_common(5)],
            "source_fingerprint": fingerprint,
            "mode": "statistics",
            "quality_verified": False,
            "notes": [
                "仅统计当前未归档记录，按事件时间归入本周。",
                "累计进面率按投递周分组，截至生成时实际面试记录；不是历史周末快照。",
                "待跟进/待复习与管道分布是生成时当前值，不冒充本周新增。",
                "规划完成按版本状态翻转计事件，包括显式恢复；不是独立任务数，新建时已完成的不计新增。",
            ],
        }

    @staticmethod
    def markdown(report: dict) -> str:
        """数字只来自受控统计，不由模型生成或改写。"""
        labels = {
            "applications_submitted": "本周投递",
            "interviews_recorded": "本周面试复盘",
            "cohort_interviewed": "投递组已记录面试",
            "cohort_interview_rate": "投递组累计进面率",
            "reviews_recorded": "本周复习",
            "knowledge_added": "本周新增知识",
            "plan_completion_events": "规划完成事件",
            "followups_due": "当前待跟进",
            "reviews_due": "当前待复习",
        }
        lines = ["# 时列周报 " + report["week_start"], "", "生成时间：" + report["as_of"], ""]
        for key, value in report["metrics"].items():
            label = labels[key]
            display = (
                "无分母，暂不计算"
                if value is None
                else (str(round(value * 100, 2)) + "%")
                if key.endswith("rate")
                else str(value)
            )
            lines.append(f"- {label}：{display}")
        lines += [
            "",
            "## 面试追问",
            *[
                f"- {item['question']}（{item['count']} 次复盘）"
                for item in report["top_questions"]
            ],
            "",
            "## 薄弱点",
            *[f"- {item['point']}（{item['count']} 次）" for item in report["top_weak_points"]],
            "",
            "## 统计口径",
            *["- " + note for note in report["notes"]],
        ]
        if report.get("focus_keys"):
            lines += [
                "",
                "## 模型排序的关注项（未改变统计数字）",
                *[
                    "- " + labels[key] + "：" + str(report["metrics"][key])
                    for key in report["focus_keys"]
                ],
            ]
        return "\n".join(lines)

    def generate(self, day: str, mode: str, confirmation: str, request_id: str = "") -> dict:
        """用户明确保存快照；模型仅排序真实指标，不自由创造统计事实。"""
        if mode not in {"statistics", "model"}:
            raise DomainError("周报方式不支持")
        if confirmation != ("发送统计进行周报增强" if mode == "model" else "生成并保存周报"):
            raise DomainError("请明确确认生成周报或模型统计外发")
        if request_id and (
            not isinstance(request_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", request_id)
        ):
            raise DomainError("周报请求标识格式不正确")
        report = self.report(day)
        try:
            configured = self.connection.public(self.connection.load()) if mode == "model" else {}
        except StorageError:
            configured = {"unavailable": True}
        operation = PrivateJson.revision(
            {
                "week": report["week_start"],
                "source": report["source_fingerprint"],
                "mode": mode,
                "connection": configured,
                "request_id": request_id,
            }
        )
        run = PrivateJson(self.root / "data/local/weekly-report-runs" / (operation + ".json"),
                          cipher=self.store.cipher)
        with run.lock():
            previous = run.read()
            if previous["data"]:
                report = previous["data"]
                report = {**report, "reused": True}
            else:
                report.update(
                    requested_mode=mode,
                    status="running" if mode == "model" else "completed",
                    operation_id=operation,
                )
                report["markdown"] = self.markdown(report)
                reserved = run.write_locked(report, "missing")
                if mode == "model":
                    try:
                        raw, metadata = request_json(
                            self.connection,
                            self.insights.policy,
                            '只返回 {"focus_keys":["真实指标key"]}，从提供的metrics选择最多三个需关注的key。不生成数字、资格结论或其他文本。',
                            {"metrics": report["metrics"]},
                        )
                        keys = (
                            raw.get("focus_keys")
                            if isinstance(raw, dict) and set(raw) == {"focus_keys"}
                            else None
                        )
                        if (
                            not isinstance(keys, list)
                            or not 1 <= len(keys) <= 3
                            or any(
                                not isinstance(key, str) or key not in report["metrics"]
                                for key in keys
                            )
                        ):
                            raise DomainError("模型关注项结构不合法，保留纯统计周报")
                        report.update(
                            mode="model",
                            focus_keys=list(dict.fromkeys(keys)),
                            model_metadata=metadata,
                            status="completed",
                        )
                    except (ToolError, DomainError, StorageError) as exc:
                        report["notes"].append(str(exc))
                        report.update(mode="fallback_statistics", status="fallback")
                    report["markdown"] = self.markdown(report)
                    run.write_locked(report, reserved["revision"])
        file = PrivateJson(
            self.root / "data/local/weekly-reports" / (report["week_start"] + ".json"),
            cipher=self.store.cipher,
        )
        with file.lock():
            previous = file.read()
            file.write_locked(report, previous["revision"])
        return {**report, "reused": report.get("reused", False)}

    def saved(self, day: str) -> dict:
        """冻结结果与当前统计分开，报告变化时不静默覆盖历史文件。"""
        live = self.report(day)
        value = PrivateJson(
            self.root / "data/local/weekly-reports" / (live["week_start"] + ".json"),
            cipher=self.store.cipher,
        ).read()
        return {
            "current": live,
            "saved": value["data"],
            "stale": bool(
                value["data"] and value["data"]["source_fingerprint"] != live["source_fingerprint"]
            ),
        }
