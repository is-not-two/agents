"""Bounded read-only business projections; no answers, private notes or model calls."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rag_tech_retriever.domains.jobs import STATUSES
from rag_tech_retriever.domains.life_planning import DomainError, text
from rag_tech_retriever.platform.mcp_policy import query_limits
from rag_tech_retriever.platform.model_connection import ModelConnection
from rag_tech_retriever.platform.record_store import RecordStore
from rag_tech_retriever.platform.weekly_report import WeeklyReport


class BusinessQueries:
    """Reuse current persisted fields and WeeklyReport statistics; never call save/generate."""

    def __init__(self, store: RecordStore, root: Path, connection: ModelConnection,
                 limits: dict | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self.store, self.root, self.connection = store, root, connection
        self.limits = query_limits(limits)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _page(self, limit: int | None, offset: int) -> tuple[int, int]:
        limit = self.limits["default_limit"] if limit is None else limit
        if (type(limit) is not int or not 1 <= limit <= self.limits["max_limit"]
                or type(offset) is not int or not 0 <= offset <= self.limits["max_offset"]):
            raise DomainError("查询条数或分页偏移超出服务器限额")
        return limit, offset

    def _pagination(self, more: bool, limit: int, offset: int) -> dict:
        capped = more and offset + limit > self.limits["max_offset"]
        return {"has_more": more, "next_offset": offset + limit if more and not capped else None,
                "pagination_limit_reached": capped}

    @contextmanager
    def _read(self) -> Iterator[Any]:
        with self.store.transaction() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(f"SET LOCAL statement_timeout = {self.limits['statement_timeout_ms']}")
            yield cur

    def jobs_search(self, company: str = "", position: str = "", status: str = "",
                    limit: int | None = None, offset: int = 0) -> dict:
        """Search actual active applications; only company/role/status/date/IDs leave DB."""
        maximum = self.limits["max_query_chars"]
        company, position = text(company, "公司", maximum), text(position, "岗位", maximum)
        if not isinstance(status, str) or (status and status not in STATUSES):
            raise DomainError("投递状态不支持")
        limit, offset = self._page(limit, offset); now = self.clock().astimezone(timezone.utc).isoformat()
        with self._read() as cur:
            cur.execute(f"""SELECT a.id,a.version,a.data->>'lead_id' AS lead_id,
                l.data->>'company' AS company,l.data->>'title' AS position,
                a.data->>'status' AS status,a.data->>'applied_at' AS applied_at,
                a.data->>'follow_up_at' AS follow_up_at
                FROM {self.store.records} a JOIN {self.store.records} l
                ON l.id=a.data->>'lead_id' AND l.kind='job_lead' AND l.deleted=FALSE
                WHERE a.kind='application' AND a.deleted=FALSE
                AND (%s='' OR strpos(lower(l.data->>'company'),lower(%s))>0)
                AND (%s='' OR strpos(lower(l.data->>'title'),lower(%s))>0)
                AND (%s='' OR a.data->>'status'=%s)
                ORDER BY a.updated_at DESC,a.id LIMIT %s OFFSET %s""",
                (company, company, position, position, status, status, limit + 1, offset))
            rows = [dict(row) for row in cur.fetchall()]
        more = len(rows) > limit
        for row in rows[:limit]:
            row["follow_up_due"] = bool(row["follow_up_at"] and row["follow_up_at"] <= now and row["status"] not in {"offered", "rejected"})
        return {"applications": rows[:limit], "returned": min(len(rows), limit), **self._pagination(more, limit, offset), "as_of": now,
                "scope": "active_applications_only", "notes": ["不含岗位原文、备注、简历或面试回答；分页不是跨请求冻结快照。"]}

    def learning_due(self, limit: int | None = None, offset: int = 0) -> dict:
        """At-or-before server time only; paused/deleted cards and answers are excluded."""
        limit, offset = self._page(limit, offset); now = self.clock().astimezone(timezone.utc).isoformat()
        maximum = self.limits["max_title_chars"]
        with self._read() as cur:
            cur.execute(f"""SELECT id,version,left(data->>'title',%s) AS title,
                length(data->>'title')>%s AS title_truncated,data->>'due_at' AS due_at,
                (data->>'repetitions')::int AS repetitions,(data->>'interval_days')::int AS interval_days
                FROM {self.store.records} WHERE kind='learning_card' AND deleted=FALSE
                AND (data->>'paused')::boolean=FALSE AND (data->>'due_at')::timestamptz<=%s::timestamptz
                ORDER BY (data->>'due_at')::timestamptz,id LIMIT %s OFFSET %s""", (maximum, maximum, now, limit + 1, offset))
            rows = [dict(row) for row in cur.fetchall()]
        return {"cards": rows[:limit], "returned": min(len(rows), limit), **self._pagination(len(rows) > limit, limit, offset), "as_of": now,
                "answers_included": False, "notes": ["只查询已经到期且未暂停的卡片；不记录复习、不推进日期。"]}

    def jobs_weekly_stats(self, day: str = "") -> dict:
        """Same event/window/cohort semantics as the Web report, statistics projection only."""
        day = text(day, "周报日期", 10)
        if day:
            try:
                selected = date.fromisoformat(day)
                if selected.isoformat() != day or selected.year < 2: raise ValueError
                selected + timedelta(days=7)
            except (ValueError, OverflowError):
                raise DomainError("请选择有效且可计算完整周窗口的YYYY-MM-DD日期") from None
        report = WeeklyReport(self.root, self.store, self.connection).report(day, now=self.clock(), read_limits={
            "max_records": self.limits["max_stats_records"], "max_versions": self.limits["max_stats_versions"],
            "statement_timeout_ms": self.limits["statement_timeout_ms"]})
        return {key: report[key] for key in ("schema", "week_start", "week_end_exclusive", "window_start_utc",
                "window_end_utc", "as_of", "metrics", "pipeline_current", "cohort_current", "source_fingerprint", "mode", "notes")}
