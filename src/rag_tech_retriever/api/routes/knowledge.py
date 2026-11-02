"""knowledge 路由：输入/领域校验与服务调用。"""

import anyio
from fastapi import APIRouter, UploadFile

from rag_tech_retriever.agent.workflow_service import WorkflowService
from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordInput
from rag_tech_retriever.domains.knowledge import validate_knowledge
from rag_tech_retriever.domains.life_planning import DomainError


def create_router(context: WorkspaceContext) -> APIRouter:
    """用服务容器创建本模块路由。"""
    router = APIRouter()
    store = context.store

    @router.post("/api/knowledge/import/markdown")
    async def markdown_preview(file: UploadFile) -> dict:
        """Upload -> structural analysis -> preview; only /confirm writes knowledge."""
        try:
            filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
            if not filename.lower().endswith((".md", ".markdown")):
                raise DomainError("请选择Markdown（.md或.markdown）文件")
            maximum = int(context.config.get("web.max_markdown_bytes", 262144))
            raw = await file.read(maximum + 1)
            if len(raw) > maximum:
                raise DomainError("Markdown超过上传大小限制")
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeError as exc:
                raise DomainError("Markdown必须使用UTF-8编码") from exc
            if "\0" in content:
                raise DomainError("文件包含二进制内容")
            service = WorkflowService(store, context.search)
            size = int(context.config.get("web.markdown_chunk_size", 1500))
            return await anyio.to_thread.run_sync(service.preview_markdown, filename, content, size)
        finally:
            await file.close()

    @router.get("/api/knowledge")
    def knowledge_list(trash: bool = False) -> list:
        return store.list("knowledge", deleted=trash)

    @router.post("/api/knowledge", status_code=201)
    def knowledge_create(payload: RecordInput) -> dict:
        return store.save("knowledge", validate_knowledge(payload.data))

    @router.put("/api/knowledge/{record_id}")
    def knowledge_update(record_id: str, payload: RecordInput) -> dict:
        return store.save("knowledge", validate_knowledge(payload.data), record_id, payload.version)

    return router
