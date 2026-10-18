"""API 组装的服务容器与表现转换；领域规则和持久化各自独立。"""

from dataclasses import dataclass
from pathlib import Path

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.common.stage_journal import StageJournal
from rag_tech_retriever.domains.life_planning import derive_plan
from rag_tech_retriever.platform.record_store import RecordStore
from rag_tech_retriever.platform.search_service import SearchService


@dataclass
class WorkspaceContext:
    """明确注入各路由的依赖，避免路由互相调用或模块全局连接。"""

    store: RecordStore
    journal: StageJournal
    search: SearchService
    exports: Path
    settings: ConfigLoader
    config: ConfigLoader


def visible(row: dict) -> dict:
    return {**row, "data": derive_plan(row["data"])} if row["kind"] == "plan" else row
