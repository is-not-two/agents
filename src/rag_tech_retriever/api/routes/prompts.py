"""提示词优化路由：一次模型调用，只改写草稿，不写库。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.platform.prompt_optimizer import OptimizeError, optimize_prompt


class PromptOptimizeInput(BaseModel):
    """草稿原文，以及调用场景；场景只用于后续扩展，不改变模型权限。"""

    text: str = Field(min_length=1, max_length=10000)
    target: str = Field(default="workspace", max_length=32)


def create_router(context: WorkspaceContext) -> APIRouter:
    """服务只在请求时读取配置与模型连接。"""
    router = APIRouter()
    prompts = ConfigLoader(context.settings.settings_path.parent / "prompts.yaml")

    @router.post("/api/prompt/optimize")
    def optimize(payload: PromptOptimizeInput) -> dict:
        draft = payload.text.strip()
        limit = int(context.config.get("web.prompt_optimizer.max_input_chars", 4000))
        if not draft:
            raise HTTPException(400, "请输入需要优化的提示词")
        if len(draft) > limit:
            raise HTTPException(400, f"提示词超过 {limit} 字符，请先精简草稿")
        system = str(prompts.get("optimizer.system", "")).strip()
        try:
            result = optimize_prompt(
                context.search.connection,
                system,
                draft,
                max_tokens=int(context.config.get("web.prompt_optimizer.max_tokens", 800)),
                timeout=int(context.config.get("web.prompt_optimizer.timeout_seconds", 25)),
            )
        except OptimizeError as exc:
            raise HTTPException(503, str(exc)) from exc
        optimized = result["optimized"]
        if len(optimized) > limit * 2:
            raise HTTPException(422, "优化结果过长，请缩短草稿后重试")
        return {"original": draft, "optimized": optimized,
                "model": result["model"], "usage": result["usage"]}

    return router
