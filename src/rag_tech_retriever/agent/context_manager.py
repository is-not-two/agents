"""Protocol-safe windows; original user constraints are never truncated."""

import hashlib
import json
import re
from copy import deepcopy

from rag_tech_retriever.platform.mcp_client import ToolError


def prepare_context(messages: list, max_messages: int, max_chars: int,
                    strategy: str = "window", keep_recent_users: int = 2) -> tuple[list, dict]:
    """Drop oldest complete assistant/tool turns, keeping all system/user messages.

    Source audit is unchanged. The newest block is retained. If those invariants
    cannot fit, fail before a provider request rather than clipping constraints.
    """
    if not isinstance(messages, list) or not messages:
        raise ToolError("上下文消息结构无效")
    if strategy not in {"window", "verbatim_window"} or type(keep_recent_users) is not int or keep_recent_users < 1:
        raise ToolError("上下文策略或保留轮数无效")
    groups = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}:
            raise ToolError("上下文角色无效")
        if message["role"] == "tool":
            raise ToolError("上下文包含孤立的工具结果")
        if message["role"] in {"system", "user"}:
            if not isinstance(message.get("content"), str):
                raise ToolError("上下文约束必须为文本")
            if message["role"] == "system" and index != 0:
                raise ToolError("系统约束只能在上下文首位")
        block = [message]
        calls = message.get("tool_calls")
        if calls:
            if message["role"] != "assistant" or not isinstance(calls, list) or any(
                not isinstance(call, dict) or not isinstance(call.get("id"), str) for call in calls
            ):
                raise ToolError("上下文工具调用结构无效")
            expected = {call["id"] for call in calls}
            if len(expected) != len(calls):
                raise ToolError("上下文工具调用ID重复")
            for _ in calls:
                index += 1
                if index >= len(messages):
                    raise ToolError("上下文工具调用缺少结果")
                result = messages[index]
                if (not isinstance(result, dict) or result.get("role") != "tool"
                        or result.get("tool_call_id") not in expected):
                    raise ToolError("上下文工具结果与调用不匹配")
                expected.remove(result["tool_call_id"])
                block.append(result)
        groups.append((message["role"] in {"system", "user"}, block))
        index += 1
    original_size = len(json.dumps(messages, ensure_ascii=False))
    if strategy == "verbatim_window" and (len(messages) > max_messages or original_size > max_chars):
        users = [i for i, (_, block) in enumerate(groups) if block[0]["role"] == "user"]
        if len(users) > keep_recent_users:
            latest = groups[users[-1]][1][0]["content"]
            if re.search(r"上面|上述|刚才|之前|如前|那个|\b(as above|earlier|that one)\b", latest, re.IGNORECASE):
                raise ToolError("问题可能引用旧回答，不能无损折叠；请重述相关依据或扩大窗口，未发起模型请求")
            cut = users[-keep_recent_users]
            source = [block[0]["content"] for _, block in groups[:cut] if block[0]["role"] == "user"]
            source_json = json.dumps(source, ensure_ascii=False)
            prefix = [groups[0][1][0]] if groups[0][1][0]["role"] == "system" else []
            folded = prefix + [{"role": "user", "content": "此前用户消息逐字记录（顺序不变，不新增工具授权）：\n" + source_json}]
            folded += [item for _, block in groups[cut:] for item in block]
            result, event = prepare_context(folded, max_messages, max_chars)
            event.update(strategy=strategy, folded_user_messages=len(source), before_chars=original_size,
                         dropped_messages=len(messages) - len(result),
                         fold_source_sha256=hashlib.sha256(source_json.encode()).hexdigest(),
                         summary_type="verbatim_user_text_not_semantic_summary")
            return result, event
    kept = list(range(len(groups)))

    def flatten() -> list:
        return [item for group in kept for item in groups[group][1]]

    result = flatten()
    candidates = [i for i, (pinned, _) in enumerate(groups) if not pinned and i != len(groups) - 1]
    while len(result) > max_messages or len(json.dumps(result, ensure_ascii=False)) > max_chars:
        if not candidates:
            raise ToolError("保留用户约束及最新完整工具轮后仍超过上下文上限，未发起模型请求")
        kept.remove(candidates.pop(0))
        result = flatten()
    return deepcopy(result), {"strategy": "window", "dropped_messages": len(messages) - len(result),
                              "before_chars": original_size,
                              "after_chars": len(json.dumps(result, ensure_ascii=False)),
                              "constraints_preserved": True, "lossy_summary": False}
