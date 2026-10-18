"""网页模型连接接口；凭据仅在服务器私有配置中保存。"""

from fastapi import APIRouter

from rag_tech_retriever.api.dependencies import WorkspaceContext


def create_router(context: WorkspaceContext) -> APIRouter:
    """配置和测试共享应用的模型连接对象。"""
    router = APIRouter()
    connection = context.search.connection

    @router.get("/api/model-connection")
    def read_connection() -> dict:
        return connection.public(connection.load())

    @router.put("/api/model-connection")
    def save_connection(payload: dict) -> dict:
        return connection.save(payload)

    @router.post("/api/model-connection/test")
    def test_connection(payload: dict) -> dict:
        return connection.test(payload)

    return router
