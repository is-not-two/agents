"""团队协作服务测试：名单校验、写操作闸门、记录落库、编排接线。

编排部分需要 agent-framework（Python 3.11+）；未安装时只跑与框架无关的校验用例。
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import ClassVar

import anyio
import pytest

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform import maf_runtime
from rag_tech_retriever.platform.team_service import TeamService


class Store:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.seq = 0

    def put(self, kind: str, data: dict) -> dict:
        self.seq += 1
        row = {"id": f"r{self.seq}", "kind": kind, "version": 1, "data": deepcopy(data)}
        self.rows[row["id"]] = row
        return row

    def get(self, record_id: str) -> dict:
        if record_id not in self.rows:
            from rag_tech_retriever.platform.record_store import RecordMissing
            raise RecordMissing("不存在")
        return deepcopy(self.rows[record_id])

    def save(self, kind: str, data: dict, record_id: str | None = None,
             version: int | None = None) -> dict:
        if record_id is None:
            return self.put(kind, data)
        row = self.rows[record_id]
        row.update(kind=kind, data=deepcopy(data), version=row["version"] + 1)
        return deepcopy(row)


class Capabilities:
    limits: ClassVar[dict] = {"max_tokens": 256, "timeout_seconds": 10, "max_context_chars": 20000}
    model_aliases: ClassVar[dict] = {}

    def __init__(self, specs: dict | None = None) -> None:
        self.specs = specs if specs is not None else {
            "code_read": {"name": "code_read", "description": "读文件", "read_only": True,
                          "input_schema": {"type": "object", "properties": {}}},
            "code_patch": {"name": "code_patch", "description": "改文件", "read_only": False,
                           "input_schema": {"type": "object", "properties": {}}},
        }
        self.executed: list[tuple[str, dict]] = []

    def validate_binding(self, profile: dict) -> dict:
        return profile

    async def catalog(self, profile: dict) -> tuple[dict, list]:
        return self.specs, []

    async def execute(self, spec, arguments, profile, skills, approved=False) -> dict:
        self.executed.append((spec["name"], arguments))
        return {"saved": True}


class Connection:
    def load(self) -> dict:
        return {"api_key": "k", "base_url": "https://example.test/v1", "model": "fake"}


def profile(title: str, prompt: str) -> dict:
    return {"title": title, "system_prompt": prompt, "model": {"alias": "", "temperature": None},
            "workspace": {"root": "", "write": "each", "shell": False}, "tool_ids": []}


def build(specs: dict | None = None, post=None):
    store = Store()
    for title, prompt in (("评估师", "[assessor] 只输出缺口"), ("面试官", "[interviewer] 只出题")):
        store.put("agent_profile", profile(title, prompt))
    caps = Capabilities(specs)
    service = TeamService(store, caps, Connection(), post=post)
    return service, store, caps


def test_rejects_non_agent_records():
    store = Store()
    store.put("workflow", {"title": "流程"})
    service = TeamService(store, Capabilities(), Connection())
    with pytest.raises(DomainError):
        anyio.run(lambda: service.run(["r1"], "任务"))


def test_rejects_too_many_members():
    store = Store()
    for index in range(5):
        store.put("agent_profile", profile(f"a{index}", "x"))
    service = TeamService(store, Capabilities(), Connection())
    with pytest.raises(DomainError):
        anyio.run(lambda: service.run([f"r{i}" for i in range(1, 6)], "任务"))


def test_write_tool_blocked_without_approval():
    service, _, caps = build()

    async def call() -> str:
        dispatch = service._dispatch({"title": "x"}, caps.specs, approved=False)
        return await dispatch("code_patch", {"path": "a.py"})

    payload = json.loads(anyio.run(call))
    assert payload["skipped"] is True
    assert caps.executed == []


def test_write_tool_runs_after_approval():
    service, _, caps = build()

    async def call() -> str:
        dispatch = service._dispatch({"title": "x"}, caps.specs, approved=True)
        return await dispatch("code_patch", {"path": "a.py"})

    assert json.loads(anyio.run(call)) == {"saved": True}
    assert caps.executed == [("code_patch", {"path": "a.py"})]


requires_maf = pytest.mark.skipif(not maf_runtime.available(), reason=maf_runtime.install_hint())


class FakeProvider:
    def __init__(self) -> None:
        self.bodies: list[dict] = []
        self.manager_calls = 0

    def __call__(self, config, body, timeout, max_chars):
        self.bodies.append(body)
        last = str(body["messages"][-1].get("content") or "")
        system = " ".join(str(m.get("content") or "") for m in body["messages"]
                          if m.get("role") == "system")
        if "Decide what to do next" in last:
            self.manager_calls += 1
            plan = [
                {"terminate": False, "reason": "先评估", "next_speaker": "评估师",
                 "final_message": None},
                {"terminate": False, "reason": "再出题", "next_speaker": "面试官",
                 "final_message": None},
                {"terminate": True, "reason": "完成", "next_speaker": None,
                 "final_message": "评估完成：缺口两项，已出一道实验设计题。"},
            ]
            reply = json.dumps(plan[min(self.manager_calls - 1, 2)], ensure_ascii=False)
        elif "[assessor]" in system:
            reply = "缺口：缺少检索对比实验经验。"
        elif "[interviewer]" in system:
            reply = "问题：如何设计召回率对比实验？"
        else:
            reply = "收到。"
        return {"choices": [{"message": {"role": "assistant", "content": reply}}]}


@requires_maf
def test_team_run_saves_record_with_turns():
    provider = FakeProvider()
    service, store, _ = build(post=provider)
    result = anyio.run(lambda: service.run(["r1", "r2"], "评估候选人张三"))

    assert result["speakers"] == ["评估师", "面试官"]
    assert result["final"].startswith("评估完成")
    assert result["model_calls"] >= 3
    saved = store.get(result["id"])
    assert saved["kind"] == "workflow_run"
    assert saved["data"]["kind"] == "team"
    assert saved["data"]["turns"][0]["author"] == "评估师"
    assert saved["data"]["agents"][0]["title"] == "评估师"
