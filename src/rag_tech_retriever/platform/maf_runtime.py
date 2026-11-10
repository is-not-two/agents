"""Microsoft Agent Framework 协作运行时适配层（可选依赖）。

边界约定：
- 全仓库只有本模块 ``import agent_framework``；业务代码只调用 ``run_team()``。
  框架升级、改包名、换实现时，改动收敛在这一个文件里。
- 未安装 MAF 时导入本模块不报错，调用时才给出可执行的安装提示。
  MAF 要求 Python 3.11+，本项目其余部分仍兼容 3.10，因此不能写成硬依赖。
- 模型通道复用 ``common.provider.post_chat``（OpenAI 兼容），不引入厂商 SDK；
  工具沿用能力注册表里的 JSON Schema，不在这里重新定义权限。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import anyio

from rag_tech_retriever.common.provider import ProviderError, post_chat
from rag_tech_retriever.domains.life_planning import DomainError

try:  # pragma: no cover - 依赖是否安装由环境决定
    from agent_framework import (
        Agent,
        BaseChatClient,
        ChatResponse,
        ChatResponseUpdate,
        FunctionInvocationLayer,
        FunctionTool,
        Message,
        ResponseStream,
    )
    from agent_framework._types import Content
    from agent_framework_orchestrations import GroupChatBuilder, MagenticBuilder

    _IMPORT_ERROR = ""
except ModuleNotFoundError as exc:  # pragma: no cover
    Agent = BaseChatClient = ChatResponse = ChatResponseUpdate = FunctionInvocationLayer = None
    FunctionTool = Message = ResponseStream = Content = GroupChatBuilder = MagenticBuilder = None
    _IMPORT_ERROR = str(exc)

INSTALL_HINT = (
    "未安装 Microsoft Agent Framework（要求 Python 3.11 及以上）："
    "pip install agent-framework-core agent-framework-orchestrations"
)


def available() -> bool:
    """运行环境是否具备 MAF；缺失原因见 ``install_hint()``。"""
    return Agent is not None


def install_hint() -> str:
    return INSTALL_HINT + (f"（当前缺失：{_IMPORT_ERROR}）" if _IMPORT_ERROR else "")


def _require() -> None:
    if not available():
        raise DomainError(install_hint())


def to_chat_messages(messages: Sequence[Any]) -> list[dict]:
    """MAF 消息 → OpenAI 兼容 messages。

    工具结果在 OpenAI 协议里是独立的一条 role=tool，不能塞进 assistant，否则模型会重复调用。
    """
    payload: list[dict] = []
    for message in messages:
        role = getattr(message, "role", None) or "user"
        texts: list[str] = []
        calls: list[dict] = []
        results: list[dict] = []
        for item in getattr(message, "contents", None) or []:
            if isinstance(item, str):
                texts.append(item)
                continue
            kind = getattr(item, "type", None) or type(item).__name__
            if kind == "text":
                texts.append(getattr(item, "text", "") or "")
            elif kind == "function_call":
                arguments = getattr(item, "arguments", None)
                calls.append({
                    "id": getattr(item, "call_id", "") or "",
                    "type": "function",
                    "function": {
                        "name": getattr(item, "name", "") or "",
                        "arguments": arguments if isinstance(arguments, str)
                        else json.dumps(arguments or {}, ensure_ascii=False),
                    },
                })
            elif kind == "function_result":
                result = getattr(item, "result", None)
                results.append({
                    "role": "tool",
                    "tool_call_id": getattr(item, "call_id", "") or "",
                    "content": result if isinstance(result, str)
                    else json.dumps(result, ensure_ascii=False, default=str),
                })
            elif kind == "function_approval_response":
                # 人工批准结果不进入模型上下文，只影响工具是否执行。
                continue
        if calls:
            payload.append({"role": "assistant", "content": "\n".join(texts), "tool_calls": calls})
        elif texts or not results:
            payload.append({"role": str(role), "content": "\n".join(texts)})
        payload.extend(results)
    return payload


def to_chat_response(message: Mapping[str, Any]) -> Any:
    """OpenAI choices[0].message → MAF ChatResponse（含工具调用）。"""
    _require()
    text = message.get("content")
    contents: list[Any] = []
    if isinstance(text, str) and text.strip():
        contents.append(Content.from_text(text))
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        contents.append(Content.from_function_call(
            call_id=str(call.get("id") or ""),
            name=str(function.get("name") or ""),
            arguments=function.get("arguments") or "{}",
        ))
    if not contents:
        contents.append(Content.from_text(""))
    return ChatResponse(messages=[Message(role="assistant", contents=contents)])


# 未安装 MAF 时退化为普通对象：模块仍可导入，调用时由 _require() 给出安装提示。
_CLIENT_BASES: tuple = (FunctionInvocationLayer, BaseChatClient) if available() else (object,)


class ProviderChatClient(*_CLIENT_BASES):
    """把 ``post_chat`` 包成 MAF 的 ChatClient。

    一个实例可以在多个 Agent 之间共享：模型配置属于服务器，属于 Agent 的只有指令与工具。
    """

    def __init__(self, limits: dict, model: str, config: Mapping[str, Any],
                 specs: Mapping[str, Any] | None = None,
                 temperature: float | None = None,
                 post: Callable[..., dict] | None = None) -> None:
        _require()
        super().__init__()
        self.limits = dict(limits)
        self.model = model
        self.config = dict(config)
        self.specs = dict(specs or {})
        self.temperature = temperature
        self.post = post or post_chat
        self.calls: list[dict] = []

    def _body(self, messages: Sequence[Any], instructions: str = "") -> dict:
        payload = to_chat_messages(messages)
        # MAF 把 Agent 指令放在 options["instructions"] 里，不写进 messages；
        # 我们的模型通道是纯 OpenAI 协议，必须自己补成 system 消息。
        if instructions and not (payload and payload[0].get("role") == "system"):
            payload.insert(0, {"role": "system", "content": instructions})
        body: dict[str, Any] = {
            "model": self.model,
            "messages": payload,
            "max_tokens": self.limits["max_tokens"],
            "stream": False,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.specs:
            body["tools"] = [{
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec.get("description", ""),
                    "parameters": spec.get("input_schema", {}),
                },
            } for spec in self.specs.values()]
            body["tool_choice"] = "auto"
        return body

    async def _produce(self, messages: Sequence[Any], instructions: str = "") -> Any:
        body = self._body(messages, instructions)
        limit = self.limits.get("max_context_chars", 120000)
        if len(json.dumps(body, ensure_ascii=False)) > limit:
            raise DomainError("上下文超过配置限制，未发起模型请求")
        self.calls.append({"messages": body["messages"], "tools": len(self.specs)})

        def request() -> dict:
            try:
                envelope = self.post(self.config, body,
                                     self.limits.get("timeout_seconds", 60), limit)
                return envelope["choices"][0]["message"]
            except ProviderError as exc:
                raise DomainError(str(exc)) from exc
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise DomainError("模型未返回可解析的响应") from exc

        return to_chat_response(await anyio.to_thread.run_sync(request))

    async def _as_stream(self, messages: Sequence[Any], instructions: str = "") -> Any:
        """把一次性响应摊成单段更新流；工具调用层只接受流式返回。"""
        response = await self._produce(messages, instructions)
        yield ChatResponseUpdate(contents=list(response.messages[0].contents), role="assistant")

    async def _inner_get_response(self, *, messages: Sequence[Any], stream: bool,
                                  options: Mapping[str, Any], **kwargs: Any) -> Any:
        instructions = str(options.get("instructions") or "")
        if stream:
            return ResponseStream(self._as_stream(messages, instructions),
                                  finalizer=ChatResponse.from_updates)
        return await self._produce(messages, instructions)


def build_tools(specs: Mapping[str, Any], dispatch: Callable[[str, dict], Awaitable[str]]) -> list:
    """能力注册表里的 JSON Schema → MAF 工具。

    工具的 schema 与只读标记一律来自注册表，Agent 无法自己给自己放权；
    非只读工具挂审批模式，由后端在调用前请求人工确认。
    """
    _require()
    tools = []
    for spec in specs.values():
        name = spec["name"]

        async def invoke(_name: str = name, **kwargs: Any) -> str:
            return await dispatch(_name, kwargs)

        tools.append(FunctionTool(
            name=name,
            description=spec.get("description", ""),
            func=invoke,
            input_model=spec.get("input_schema") or {"type": "object", "properties": {}},
            approval_mode=None if spec.get("read_only") else "always_require",
        ))
    return tools


def build_agent(client: Any, profile: Mapping[str, Any], tools: Sequence[Any] | None = None) -> Any:
    """领域里的 agent_profile → MAF Agent。指令只来自 profile，不拼接外部文本。"""
    _require()
    return Agent(
        client=client,
        name=str(profile.get("key") or profile.get("title") or "agent"),
        description=str(profile.get("title") or ""),
        instructions=str(profile.get("system_prompt") or ""),
        tools=list(tools or []),
    )


def _event_texts(event: Any) -> tuple[str, list[str]]:
    """从工作流事件里取出「谁说了什么」。

    MAF 把发言包装成 AgentResponseUpdate（可能分多段累积），工具/请求类事件没有正文，
    这里只认 assistant 角色的增量文本，避免把内部请求当成回答。
    """
    author = str(getattr(event, "executor_id", None) or getattr(event, "author_name", None) or "")
    data = getattr(event, "data", None)
    items = data if isinstance(data, list) else [data]
    texts: list[str] = []
    for item in items:
        if type(item).__name__ not in {"AgentResponseUpdate", "ChatResponseUpdate"}:
            continue
        if getattr(item, "role", None) not in (None, "assistant"):
            continue
        text = getattr(item, "text", "") or ""
        if text.strip():
            texts.append(text)
    return author, texts


async def run_team(task: str, agents: Sequence[Any], manager: Any, *,
                   mode: str = "group_chat", max_rounds: int = 6) -> dict:
    """按指定拓扑驱动一组 Agent，返回发言记录与最终答复。

    group_chat：主持人每轮选下一个发言人，适合「分工 + 互相看对方结论」。
    magentic：给一句话目标，由框架自己规划、派活、看进度台账并重规划。
    """
    _require()
    if mode == "group_chat":
        workflow = (GroupChatBuilder(participants=list(agents), orchestrator_agent=manager)
                    .with_max_rounds(max_rounds).build())
    elif mode == "magentic":
        # manager_agent 收的是 Agent；manager= 要的是 MagenticManagerBase，传错会直接报错。
        workflow = MagenticBuilder(participants=list(agents), manager_agent=manager,
                                   max_round_count=max_rounds).build()
    else:
        raise DomainError("团队模式只支持 group_chat / magentic")

    manager_name = str(getattr(manager, "name", "") or "manager")
    turns: list[dict] = []
    async for event in workflow.run(task, stream=True):
        author, texts = _event_texts(event)
        for text in texts:
            if turns and turns[-1]["author"] == author and text.startswith(turns[-1]["text"]):
                turns[-1]["text"] = text  # 增量累积，保留最长的那次
            elif turns and turns[-1]["author"] == author and turns[-1]["text"].endswith(text):
                continue
            else:
                turns.append({"author": author, "text": text})

    spoken = [turn for turn in turns if turn["author"] and turn["author"] != manager_name]
    summary = [turn for turn in turns if turn["author"] == manager_name]
    return {
        "mode": mode,
        "turns": turns,
        "final": (summary[-1]["text"] if summary else "") or (spoken[-1]["text"] if spoken else ""),
        "speakers": [turn["author"] for turn in spoken],
    }
