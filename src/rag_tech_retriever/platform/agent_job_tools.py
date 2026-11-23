"""Agent 求职数据的只读投影：把岗位 / 投递 / 复盘 / 能力 / 简历投影成可引用的摘要。

边界
- 只读：不写库、不改状态、不调用模型。
- 只投影白名单字段；JD 与简历正文按字符上限截断并标注 truncated。
- 数据源是工作台的求职记录，不包含私密日记 / 愿望 / 账户凭据。
- 全部是纯函数，便于在没有数据库的门禁里测试。
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

JOB_KINDS = ("job_lead", "application", "interview_report", "company_capability",
             "resume_version")

DEFAULT_LIMIT = 10
MAX_LIMIT = 20
SNIPPET_CHARS = 160
JD_CHARS = 6000
RESUME_CHARS = 3000
NOTES_CHARS = 500


def _clip(value: object, limit: int) -> tuple[str, bool]:
    shown = str(value or "").strip()
    if len(shown) <= limit:
        return shown, False
    return shown[:limit], True


def _one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def _joined(value: object) -> str:
    """列表按顿号拼接；非列表原样转成一行，避免出现 "['a', 'b']" 这种表示。"""
    if isinstance(value, list):
        return _one_line("、".join(_one_line(item) for item in value if _one_line(item)))
    return _one_line(value)


def summarize(kind: str, data: dict) -> dict:
    """列表用的紧凑摘要；不含 JD / 简历正文。"""
    data = data if isinstance(data, dict) else {}
    if kind == "job_lead":
        jd, _ = _clip(data.get("jd_text"), SNIPPET_CHARS)
        return {"title": _one_line(data.get("title"))[:120],
                "company": _one_line(data.get("company"))[:120],
                "jd_snippet": _one_line(jd),
                "jd_chars": len(str(data.get("jd_text") or ""))}
    if kind == "application":
        return {"title": _one_line(data.get("title"))[:120],
                "status": _one_line(data.get("status"))[:40],
                "channel": _one_line(data.get("channel"))[:40],
                "applied_at": _one_line(data.get("applied_at"))[:40],
                "follow_up_at": _one_line(data.get("follow_up_at"))[:40],
                "lead_id": _one_line(data.get("lead_id"))[:100]}
    if kind == "interview_report":
        questions = data.get("questions")
        weak = data.get("weak_points")
        return {"title": _one_line(data.get("title"))[:120],
                "round": data.get("round"),
                "interviewed_at": _one_line(data.get("interviewed_at"))[:40],
                "questions": len(questions) if isinstance(questions, list) else 0,
                "weak_points": _joined(weak)[:160]}
    if kind == "company_capability":
        items = data.get("capabilities")
        rows = items if isinstance(items, list) else []
        must = sum(1 for row in rows if isinstance(row, dict) and row.get("requirement") == "must")
        return {"company": _one_line(data.get("company"))[:120],
                "title": _one_line(data.get("title"))[:120],
                "capabilities": len(rows), "must": must}
    if kind == "resume_version":
        highlights = data.get("highlights")
        return {"title": _one_line(data.get("title"))[:120],
                "file_name": _one_line(data.get("file_name"))[:160],
                "parse_status": _one_line(data.get("parse_status"))[:40],
                "highlights": _joined(highlights)[:160]}
    return {}


def _haystack(kind: str, data: dict) -> str:
    if kind == "job_lead":
        parts = (data.get("title"), data.get("company"), data.get("jd_text"), data.get("notes"))
    elif kind == "application":
        parts = (data.get("title"), data.get("status"), data.get("channel"), data.get("notes"))
    elif kind == "interview_report":
        parts = (data.get("title"), data.get("weak_points"), data.get("questions"))
    elif kind == "company_capability":
        parts = (data.get("company"), data.get("title"), data.get("capabilities"))
    else:
        parts = (data.get("title"), data.get("file_name"), data.get("highlights"))
    return " ".join(_one_line(part) for part in parts).lower()


def matches(kind: str, data: dict, query: str, company: str) -> bool:
    """query 与 company 都不区分大小写；company 只对带公司字段的 kind 生效。"""
    text = _haystack(kind, data)
    if query and query.strip().lower() not in text:
        return False
    if company and company.strip():
        name = _one_line(data.get("company")).lower()
        if company.strip().lower() not in name:
            return False
    return True


def search(rows: Iterable[dict], query: str = "", company: str = "",
           kinds: Sequence[str] = JOB_KINDS, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """按 kind 过滤并要求匹配，再按更新时间倒序截断；只返回可引用摘要。"""
    allowed = [kind for kind in kinds if kind in JOB_KINDS] or list(JOB_KINDS)
    size = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    found = []
    for row in rows:
        kind = row.get("kind")
        if kind not in allowed:
            continue
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        if not matches(kind, data, query, company):
            continue
        found.append({"id": row.get("id"), "kind": kind, "version": row.get("version"),
                      "updated_at": row.get("updated_at"), "summary": summarize(kind, data)})
    found.sort(key=lambda item: (str(item.get("updated_at") or ""), str(item.get("id"))),
               reverse=True)
    return found[:size]


def detail(row: dict) -> dict:
    """单条详情：白名单字段 + 正文截断；返回 truncated 说明被截断的字段。"""
    kind = row.get("kind")
    if kind not in JOB_KINDS:
        raise ValueError("条目不是求职记录")
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    fields: dict = {}
    truncated: list[str] = []

    def take(name: str, limit: int | None = None) -> None:
        value = data.get(name)
        if value is None:
            return
        if limit is None:
            fields[name] = value
            return
        shown, cut = _clip(value, limit)
        fields[name] = shown
        if cut:
            truncated.append(name)

    if kind == "job_lead":
        take("title"); take("company"); take("jd_text", JD_CHARS); take("notes", NOTES_CHARS)
    elif kind == "application":
        for name in ("title", "status", "channel", "applied_at", "follow_up_at",
                     "lead_id", "resume_version_id"):
            take(name)
        take("notes", NOTES_CHARS)
    elif kind == "interview_report":
        for name in ("title", "round", "interviewed_at", "application_id",
                     "questions", "weak_points", "next_actions"):
            take(name)
    elif kind == "company_capability":
        take("company"); take("title"); take("capabilities")
    else:
        for name in ("title", "file_name", "parse_status", "highlights"):
            take(name)
        take("text", RESUME_CHARS)

    return {"id": row.get("id"), "kind": kind, "version": row.get("version"),
            "updated_at": row.get("updated_at"), "data": fields, "truncated": truncated}
