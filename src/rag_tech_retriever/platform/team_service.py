"""团队协作服务：把现有 agent_profile 交给 MAF 编排，结果落成一条可追溯的运行记录。

职责边界：
- 只读工具直接执行；写工具需要「运行前批准」，未批准时把结果如实回给模型而不是静默跳过。
- 记录里保存完整的发言顺序与最终答复，界面复用现有运行详情视图。
- 不在这里 new 任何权限：工具集合仍来自能力注册表，Agent 只能用它被授予的那份。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform import maf_runtime

MAX_TEAM_SIZE = 4
MANAGER_PROMPT = (
    "你是多 Agent 团队的主持人。你只决定下一个发言人和是否结束，不代替成员回答。"
    "优先让还没发言的成员先讲；成员之间需要补充或纠错时，可以让已发言的成员再讲一次。"
    "当团队已经覆盖任务要求，或再讨论也不会产生新信息时结束，并把成员结论合并成一段终稿。"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TeamService:
    """一个团队 = 若干已有 Agent + 一段目标描述，编排细节交给 MAF。"""

    def __init__(self, store: Any, capabilities: Any, connection: Any,
                 post: Callable[..., dict] | None = None) -> None:
        self.store = store
        self.capabilities = capabilities
        self.connection = connection
        self.post = post

    def _agent_row(self, agent_id: str) -> dict:
        row = self.store.get(agent_id)
        if row["kind"] != "agent_profile":
            raise DomainError("只有 Agent 可以加入团队")
        return row

    def _dispatch(self, profile: dict, specs: dict, approved: bool) -> Callable[..., Awaitable[str]]:
        async def dispatch(name: str, arguments: dict) -> str:
            spec = specs.get(name)
            if not spec:
                return json.dumps({"error": "该工具未授权给这个成员"}, ensure_ascii=False)
            if not spec["read_only"] and not approved:
                return json.dumps({"skipped": True,
                                   "reason": "写操作需要在运行前批准；本次未执行，请改用只读方式推进"},
                                  ensure_ascii=False)
            result = await self.capabilities.execute(spec, arguments, profile, [], approved=approved)
            return json.dumps(result, ensure_ascii=False, default=str)[:6000]
        return dispatch

    async def run(self, agent_ids: list[str], task: str, mode: str = "group_chat",
                  max_rounds: int = 6, approved: bool = False) -> dict:
        if not maf_runtime.available():
            raise DomainError(maf_runtime.install_hint())
        ids = list(dict.fromkeys(agent_ids))
        if not 1 <= len(ids) <= MAX_TEAM_SIZE:
            raise DomainError(f"团队成员数量需在 1 到 {MAX_TEAM_SIZE} 之间")
        config = self.connection.load()
        if not all(config.get(key) for key in ("api_key", "base_url", "model")):
            raise DomainError("尚未配置模型连接；团队协作需要支持工具调用的模型")

        limits = self.capabilities.limits
        aliases = getattr(self.capabilities, "model_aliases", {})
        members: list[Any] = []
        roster: list[dict] = []
        clients: list[Any] = []
        for agent_id in ids:
            row = self._agent_row(agent_id)
            profile = self.capabilities.validate_binding(validate_agent(row["data"]))
            specs, _ = await self.capabilities.catalog(profile)
            alias = profile["model"]["alias"]
            if alias and alias not in aliases:
                raise DomainError(f"模型别名已撤销：{alias}")
            client = maf_runtime.ProviderChatClient(
                limits, aliases[alias] if alias else config["model"], config, specs,
                profile["model"].get("temperature"), post=self.post)
            clients.append(client)
            members.append(maf_runtime.build_agent(
                client, {**profile, "key": profile["title"]},
                maf_runtime.build_tools(specs, self._dispatch(profile, specs, approved))))
            roster.append({"id": agent_id, "title": profile["title"],
                           "tools": sorted(specs)})

        manager_client = maf_runtime.ProviderChatClient(
            limits, config["model"], config, None, post=self.post)
        clients.append(manager_client)
        manager = maf_runtime.build_agent(
            manager_client, {"key": "manager", "title": "团队主持人",
                             "system_prompt": MANAGER_PROMPT})

        started = _now()
        result = await maf_runtime.run_team(task, members, manager, mode=mode,
                                            max_rounds=max_rounds)
        row = self.store.save("workflow_run", {
            "kind": "team",
            "title": task[:80],
            "status": "completed",
            "mode": mode,
            "approved": approved,
            "agents": roster,
            "input": {"task": task},
            "turns": result["turns"],
            "speakers": result["speakers"],
            "result": {"answer": result["final"], "notes": []},
            "started_at": started,
            "finished_at": _now(),
            "model_calls": sum(len(client.calls) for client in clients),
        })
        return {"id": row["id"], "version": row["version"], "mode": mode,
                "turns": result["turns"], "final": result["final"],
                "speakers": result["speakers"], "agents": roster,
                "model_calls": row["data"]["model_calls"]}
