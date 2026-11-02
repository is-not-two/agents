"""检索质量评测路由：跑评测集、看召回率、对比重排开关。

鉴权沿用全局 protect 中间件；本模块只读运行，不写任何业务记录。
评测结果只回传，不落库——每次点击都是即时的当前状态，避免历史数据冒充现状。
"""

from fastapi import APIRouter, HTTPException

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.common.config_loader import PROJECT_ROOT
from rag_tech_retriever.platform.eval_service import (
    EvalError,
    load_questions,
    run_evaluation,
)


def create_router(context: WorkspaceContext) -> APIRouter:
    """用服务容器创建评测路由。"""
    router = APIRouter(prefix="/api/eval", tags=["eval"])
    search = context.search

    def questions_path():
        """评测题集固定路径（与 V1 基线脚本同一份，保证口径一致）。"""
        return PROJECT_ROOT / "data" / "processed" / "eval_questions.json"

    @router.get("/questions")
    def questions() -> dict:
        """返回评测题集摘要（不含参考答案正文，避免前端泄漏答案）。"""
        try:
            items = load_questions(questions_path())
        except EvalError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {
            "total": len(items),
            "items": [
                {
                    "qid": item["qid"],
                    "type": item.get("type", ""),
                    "question": item["question"],
                    "anchors": item["must_retrieve"],
                }
                for item in items
            ],
        }

    @router.post("/run")
    def run(rerank: bool = True) -> dict:
        """跑整套评测。

        Args:
            rerank: 是否启用重排；False 时按向量相似度原序，用于对照。

        Returns:
            逐题结果与 top-1/3/5 召回率；向量链路不可用时回 503 并说明原因。
        """
        try:
            items = load_questions(questions_path())
        except EvalError as exc:
            raise HTTPException(503, str(exc)) from exc
        try:
            return run_evaluation(search, items, namespace="tech_doc", rerank=rerank)
        except (RuntimeError, OSError, ValueError, ImportError) as exc:
            # 模型/依赖/数据库任一层不可用：明确降级说明，不冒充「0% 召回」
            raise HTTPException(503, f"向量检索不可用，无法评测：{exc}") from exc

    return router
