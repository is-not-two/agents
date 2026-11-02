"""对话检索接口：多轮消息 → 检索引用 + 可选生成。

普通模式取最后一条用户消息，经规则分流为短答/人工确认入口/只读检索。
显式指定Agent或run与实际版本且generate=true时，复用服务器持有的Agent会话；
不会把客户端assistant历史当真实工具证据或权限。
"""

from fastapi import APIRouter, HTTPException

from rag_tech_retriever.agent.intent_classifier import route_intent
from rag_tech_retriever.api.dependencies import WorkspaceContext

_MAX_TURNS = 20
_MAX_MESSAGE = 2000

_VALID = {"all", "personal", "docs", "planning"}


def create_router(context: WorkspaceContext) -> APIRouter:
    router = APIRouter()
    search = context.search

    @router.post("/api/chat")
    async def chat(payload: dict) -> dict:
        messages = payload.get("messages", [])
        if not isinstance(messages, list) or not messages or len(messages) > _MAX_TURNS:
            raise HTTPException(400, f"messages 必须为 1..{_MAX_TURNS} 条")
        for item in messages:
            if (
                not isinstance(item, dict)
                or item.get("role") not in {"user", "assistant"}
                or not isinstance(item.get("content"), str)
                or not item["content"].strip()
                or len(item["content"]) > _MAX_MESSAGE
            ):
                raise HTTPException(400, "每条消息需为 user/assistant 且内容非空、不超长")
        scope = payload.get("scope", "docs")
        mode = payload.get("mode", "text")
        generate = payload.get("generate", False)
        if type(generate) is not bool:
            raise HTTPException(400, "generate 必须是布尔值，不接受字符串开关")
        if not isinstance(scope, str) or scope not in _VALID or not isinstance(mode, str) or mode not in {"text", "vector"}:
            raise HTTPException(400, "scope 或 mode 取值不合法")
        user_messages = [m for m in messages if m["role"] == "user"]
        if not user_messages:
            raise HTTPException(400, "至少需要一条 user 消息")
        last_user = user_messages[-1]["content"].strip()
        routing = route_intent(last_user)
        namespace = payload.get("namespace")
        if namespace is not None:
            search.catalog.select(namespace)
        has_agent, has_run = "agent_id" in payload, "run_id" in payload
        if has_agent or has_run:
            if namespace is not None:
                raise HTTPException(400, "工具会话使用服务器默认语料域，不能以聊天参数覆盖")
            if has_agent and has_run:
                raise HTTPException(400, "agent_id 与 run_id 不能同时提供")
            if not generate:
                raise HTTPException(400, "执行工具型Agent需明确设置generate:true；可能调用模型并计费")
            field, version_field = ("agent_id", "agent_version") if has_agent else ("run_id", "run_version")
            identity, version = payload.get(field), payload.get(version_field)
            if not isinstance(identity, str) or not identity or type(version) is not int or version < 1:
                raise HTTPException(400, "必须提供有效标识及看到的整数版本")
            if has_agent:
                row = await context.runtime.start(identity, version, last_user)
            else:
                row = await context.runtime.continue_run(identity, version, last_user)
            result = row["data"]["result"]
            return {"query": last_user, "turns": len(messages), "engine": "Agent服务器会话",
                    "answer": result.get("answer", ""), "hits": result.get("hits", []),
                    "notes": result.get("notes", []), "run": row,
                    "routing": {**routing, "selected": "agent_runtime", "client_history_used": False}}
        if routing["selected"] in {"smalltalk", "write_gate"}:
            greeting = context.config.get("web.chat.greeting", "你好，我可以检索知识与技术文档；需要写入时会引导你确认。")
            hint = context.config.get("web.chat.write_hint", "尚未执行写入。请前往资料入库或Agent工作室，核对内容后人工确认。")
            return {"query": last_user, "turns": len(messages), "hits": [],
                    "answer": greeting if routing["selected"] == "smalltalk" else hint,
                    "notes": [] if routing["selected"] == "smalltalk" else ["此入口不会自动保存、删除或外发"],
                    "engine": "规则短答" if routing["selected"] == "smalltalk" else "人工确认入口",
                    "routing": routing}
        result = search.query(last_user, scope, mode, generate) if namespace is None else search.query(last_user, scope, mode, generate, namespace)
        result["turns"] = len(messages)
        result["routing"] = routing
        return result

    return router
