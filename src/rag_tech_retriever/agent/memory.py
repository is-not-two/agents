"""Per-agent, explicitly confirmed memory; never part of public backups."""

import hashlib
import json
import re
from unicodedata import normalize

from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.domains.life_planning import DomainError, text
from rag_tech_retriever.platform.mcp_client import ToolError
from rag_tech_retriever.platform.record_store import RecordMissing, RecordStore, VersionConflict


def validate_memory(content: str, max_chars: int) -> str:
    """Memory is bounded plain text, not credentials, executable instructions or grants."""
    value = text(content, "长期记忆内容", max_chars, True)
    if "\0" in value:
        raise DomainError("长期记忆必须是纯文本")
    return value


def project_scope(value: str) -> str:
    """An explicit project key; the empty key only matches legacy memory."""
    key = text(value, "记忆项目", 80)
    if any(char in key for char in "\x00\r\n"):
        raise DomainError("记忆项目必须是单行文本")
    return normalize("NFC", key)


class AgentMemory:
    """Lock the owner profile through proposal/decision; model output cannot confirm."""

    def __init__(self, store: RecordStore, limits: dict) -> None:
        self.store, self.limits = store, limits

    def _agent(self, cur, agent_id: str, version: int | None = None) -> dict:
        cur.execute(f"SELECT * FROM {self.store.records} WHERE id=%s FOR UPDATE", (agent_id,))
        raw = cur.fetchone()
        if not raw or raw["deleted"] or raw["kind"] != "agent_profile":
            raise RecordMissing("Agent不存在")
        row = self.store._serialize(raw)
        if version is not None and row["version"] != version:
            raise VersionConflict("Agent版本已改变，请刷新后重新确认")
        return row

    def _rows(self, cur, agent_id: str) -> list:
        cur.execute(f"SELECT * FROM {self.store.records} WHERE kind='agent_memory' "
                    "AND data->>'agent_id'=%s AND NOT deleted ORDER BY id", (agent_id,))
        return [self.store._serialize(row) for row in cur.fetchall()]

    def list(self, agent_id: str, project: str = "") -> list:
        """Show pending and historical decisions; only confirmed entries are projected."""
        project = project_scope(project)
        with self.store.transaction() as cur:
            self._agent(cur, agent_id)
            return [row for row in self._rows(cur, agent_id) if row["data"].get("project", "") == project]

    def propose(self, agent_id: str, version: int, content: str, request_id: str, *,
                project: str = "", source_title: str = "") -> dict:
        """Stable request identity makes retries return the original pending decision."""
        value = validate_memory(content, self.limits["max_memory_chars"])
        project = project_scope(project)
        source_title = text(source_title, "Markdown 文件名", 160)
        if source_title and (not project or any(char in source_title for char in "/\\\x00\r\n")
                             or not source_title.lower().endswith((".md", ".markdown"))):
            raise DomainError("导入笔记需要项目和 Markdown 文件名，不接受文件路径")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_id):
            raise DomainError("记忆请求标识无效")
        key = json.dumps([agent_id, project, request_id]) if project else agent_id + ":" + request_id
        identity = hashlib.sha256(key.encode()).hexdigest()[:32]
        with self.store.transaction() as cur:
            agent = self._agent(cur, agent_id, version)
            if validate_agent(agent["data"])["memory"]["scope"] != "persistent":
                raise DomainError("请先显式开启此Agent的长期记忆")
            rows = self._rows(cur, agent_id)
            existing = next((row for row in rows if row["id"] == identity), None)
            if existing:
                if (existing["data"]["content"] != value
                        or existing["data"].get("source_title", "") != source_title):
                    raise VersionConflict("同一请求标识不能改写记忆内容")
                return existing
            if sum(row["data"]["state"] in {"pending", "confirmed"} for row in rows) >= self.limits["max_memory_items"]:
                raise DomainError("记忆条目达到上限，请先拒绝或遗忘不再需要的内容")
            return self.store._save(cur, "agent_memory", {"agent_id": agent_id,
                "agent_version": version, "content": value, "state": "pending",
                "project": project, "source_title": source_title}, identity, None)

    def decide(self, agent_id: str, memory_id: str, version: int, agent_version: int,
               action: str, confirmation: str, *, project: str = "") -> dict:
        """No generic restore can resurrect a rejected or forgotten memory."""
        required = {"confirm": "确认保存长期记忆", "reject": "拒绝记忆", "forget": "确认遗忘"}
        if action not in required or confirmation != required[action]:
            raise DomainError("请逐条阅读后明确确认记忆操作")
        project = project_scope(project)
        with self.store.transaction() as cur:
            agent = self._agent(cur, agent_id, agent_version)
            rows = self._rows(cur, agent_id)
            row = next((item for item in rows if item["id"] == memory_id), None)
            if not row or row["data"].get("project", "") != project:
                raise RecordMissing("此Agent的记忆不存在")
            if row["version"] != version:
                raise VersionConflict("记忆已处理或版本改变，请刷新")
            data = row["data"]
            if action in {"confirm", "reject"} and data["state"] != "pending":
                raise VersionConflict("记忆候选已经处理，不会重放")
            if action == "forget" and data["state"] != "confirmed":
                raise VersionConflict("只能遗忘当前生效的记忆")
            if action == "confirm" and (data["agent_version"] != agent_version or
                    validate_agent(agent["data"])["memory"]["scope"] != "persistent"):
                raise VersionConflict("候选对应的Agent授权已变化，请重新提出候选")
            state = {"confirm": "confirmed", "reject": "rejected", "forget": "forgotten"}[action]
            return self.store._save(cur, "agent_memory", {**data, "state": state}, memory_id, version)

    def context(self, agent_id: str, project: str = "") -> tuple[list, str]:
        """Project only current confirmed facts; fail rather than silently omit facts."""
        rows = self.list(agent_id, project)
        facts = []
        for row in rows:
            if row["data"]["state"] == "confirmed":
                fact = {"id": row["id"], "version": row["version"], "content": row["data"]["content"]}
                if title := row["data"].get("source_title"):
                    fact["source_title"] = title
                facts.append(fact)
        raw = json.dumps(facts, ensure_ascii=False)
        if len(raw) > self.limits["max_memory_context_chars"]:
            raise ToolError("已确认长期记忆超过上下文配额，请整理或遗忘部分条目")
        return facts, hashlib.sha256(raw.encode()).hexdigest()
