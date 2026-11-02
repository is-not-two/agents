"""Zero-cost intent hints, never authorization or a substitute for tool checks."""

import re


def classify_intent(query: str) -> dict:
    """Conservative rule evidence; mixed or uncertain requests stay unknown."""
    write = bool(re.search(r"保存|删除|修改|发送|记住|写入|\b(save|delete|send|remember|update)\b", query, re.IGNORECASE))
    search = bool(re.search(r"查找|查询|检索|搜索|资料|\b(search|find|lookup)\b", query, re.IGNORECASE))
    question = bool(re.search(r"如何|怎么|是什么|用法|定义|原理|\b(how|what)\b", query, re.IGNORECASE))
    greeting = bool(re.fullmatch(r"\s*(你好|您好|谢谢|hi|hello|thanks)[!！。.\s]*", query, re.IGNORECASE))
    kind = "search" if write and question else "unknown" if write and search else "write" if write else "search" if search else "smalltalk" if greeting else "unknown"
    return {"intent": kind, "source": "rules", "authority": False, "model_called": False,
            "write_signal": write, "informational_question": question}


def route_intent(query: str) -> dict:
    """Select a real readonly/chat/manual-gate branch, never authorize an effect."""
    result = classify_intent(query)
    selected = "smalltalk" if result["intent"] == "smalltalk" else "write_gate" if (
        result["write_signal"] and not result["informational_question"]) else "search"
    return {**result, "selected": selected, "requires_confirmation": selected == "write_gate"}
