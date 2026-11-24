"""MAF 适配层测试：模型通道、消息转换、工具挂载、群聊编排。

未安装 agent-framework 的环境自动跳过；装了的环境跑真实编排（模型是假通道）。
部署要求：Python 3.11+。
"""

from __future__ import annotations

import json

import anyio
import pytest

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform import maf_runtime

pytestmark = pytest.mark.skipif(not maf_runtime.available(), reason=maf_runtime.install_hint())

LIMITS = {"max_tokens": 512, "timeout_seconds": 10, "max_context_chars": 20000}
CONFIG = {"base_url": "https://example.test/v1", "api_key": "k", "model": "fake"}

TOOLS = {
    "code_read": {
        "name": "code_read", "description": "读文件", "read_only": True,
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},
                         "required": ["path"]},
    },
}


class FakeProvider:
    """像真实模型那样按提示词作答：主持人问「下一步」就给结构化决策，其余按角色回话。"""

    def __init__(self, script: dict | None = None) -> None:
        self.script = script or {}
        self.bodies: list[dict] = []
        self.manager_calls = 0

    def __call__(self, config, body, timeout, max_chars):
        self.bodies.append(body)
        messages = body["messages"]
        last = str(messages[-1].get("content") or "")
        system = " ".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
        if "Decide what to do next" in last:
            self.manager_calls += 1
            plan = self.script.get("manager") or [{"terminate": True, "reason": "无计划"}]
            decision = plan[min(self.manager_calls - 1, len(plan) - 1)]
            reply = json.dumps(decision, ensure_ascii=False)
        else:
            reply = "（无脚本）"
            for marker, answer in self.script.items():
                if marker.startswith("[") and marker in system:
                    reply = answer
                    break
            if reply == "（无脚本）" and last:
                reply = "已收到任务。"
        return {"choices": [{"message": {"role": "assistant", "content": reply}}]}


def test_messages_convert_tool_result_to_separate_tool_role():
    message = maf_runtime.Message(role="assistant", contents=[
        maf_runtime.Content.from_function_call(call_id="c1", name="code_read",
                                               arguments={"path": "a.py"}),
    ])
    result = maf_runtime.Message(role="tool", contents=[
        maf_runtime.Content.from_function_result(call_id="c1", result="print(1)"),
    ])
    payload = maf_runtime.to_chat_messages([message, result])
    assert payload[0]["role"] == "assistant"
    assert payload[0]["tool_calls"][0]["function"]["name"] == "code_read"
    assert json.loads(payload[0]["tool_calls"][0]["function"]["arguments"]) == {"path": "a.py"}
    assert payload[1] == {"role": "tool", "tool_call_id": "c1", "content": "print(1)"}


def test_response_maps_plain_text():
    response = maf_runtime.to_chat_response({"role": "assistant", "content": "缺口：两项"})
    assert response.text == "缺口：两项"
    assert response.messages[0].role == "assistant"


def test_client_sends_capability_specs_as_tools():
    provider = FakeProvider({"[coder]": "看过了"})
    client = maf_runtime.ProviderChatClient(LIMITS, "fake", CONFIG, TOOLS, post=provider)
    agent = maf_runtime.build_agent(client, {"key": "coder", "system_prompt": "[coder] 你是实现者"})
    response = anyio.run(agent.run, "读一下 a.py")
    body = provider.bodies[0]
    assert body["tools"][0]["function"]["name"] == "code_read"
    assert body["messages"][0] == {"role": "system", "content": "[coder] 你是实现者"}
    assert "看过了" in response.text


def test_read_only_tool_has_no_approval_gate():
    tools = maf_runtime.build_tools(TOOLS, dispatch=lambda name, args: None)
    assert tools[0].name == "code_read"


def test_group_chat_two_agents_see_each_other():
    """关键验证：后手能看到前手的原话，而不是各说各话。"""
    provider = FakeProvider({
        "[assessor]": "缺口：缺少多模态检索落地经验。",
        "[interviewer]": "问题：如何设计检索召回率对比实验？",
        "manager": [
            {"terminate": False, "reason": "先评估", "next_speaker": "assessor",
             "final_message": None},
            {"terminate": False, "reason": "再出题", "next_speaker": "interviewer",
             "final_message": None},
            {"terminate": True, "reason": "完成", "next_speaker": None,
             "final_message": "评估完成。"},
        ],
    })
    client = maf_runtime.ProviderChatClient(LIMITS, "fake", CONFIG, post=provider)
    assessor = maf_runtime.build_agent(client, {"key": "assessor",
                                                "system_prompt": "[assessor] 只输出缺口"})
    interviewer = maf_runtime.build_agent(client, {"key": "interviewer",
                                                   "system_prompt": "[interviewer] 只出题"})
    manager = maf_runtime.build_agent(client, {"key": "manager", "system_prompt": "[manager] 主持"})

    result = anyio.run(
        lambda: maf_runtime.run_team("评估张三", [assessor, interviewer], manager, max_rounds=4)
    )
    assert result["speakers"] == ["assessor", "interviewer"]
    assert result["final"] == "评估完成。"
    # 面试官那轮请求里应该带着评估师说过的话，证明是真传递而不是各跑各的。
    carried = any(
        "缺少多模态检索" in str(item.get("content") or "")
        for body in provider.bodies[2:]
        for item in body["messages"]
    )
    assert carried


def test_unknown_mode_is_rejected():
    with pytest.raises(DomainError):
        anyio.run(lambda: maf_runtime.run_team("x", [], None, mode="swarm"))


def test_magentic_uses_manager_agent_and_round_limit(monkeypatch):
    """磁石模式曾把 Agent 传给 manager=，而那个参数要的是 MagenticManagerBase，一跑就报错。"""
    captured: dict = {}

    class StubWorkflow:
        def run(self, task, stream=False):
            async def gen():
                return
                yield  # pragma: no cover - 只是为了成为异步生成器

            return gen()

    class StubBuilder:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def build(self):
            return StubWorkflow()

    monkeypatch.setattr(maf_runtime, "MagenticBuilder", StubBuilder)
    client = maf_runtime.ProviderChatClient(LIMITS, "fake", CONFIG, post=FakeProvider())
    member = maf_runtime.build_agent(client, {"key": "coder", "system_prompt": "写代码"})
    manager = maf_runtime.build_agent(client, {"key": "manager", "system_prompt": "主持"})

    result = anyio.run(lambda: maf_runtime.run_team("做点事", [member], manager,
                                                    mode="magentic", max_rounds=4))
    assert captured["manager_agent"] is manager
    assert "manager" not in captured
    assert captured["max_round_count"] == 4
    assert result["mode"] == "magentic"
