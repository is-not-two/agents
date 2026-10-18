"""Web 请求契约；不处理存储和页面。"""

from pydantic import BaseModel, Field


class RecordInput(BaseModel):
    """正文及读到的版本，用于冲突保护。"""

    data: dict
    version: int | None = Field(default=None, ge=1)


class RestoreInput(BaseModel):
    """历史版本及当前版本。"""

    target_version: int = Field(ge=1)
    current_version: int = Field(ge=1)


class QueryInput(BaseModel):
    """查询文本、范围与模式。"""

    query: str = Field(min_length=1, max_length=1000)
    scope: str = "all"
    mode: str = "text"
    generate: bool = False


class StageInput(BaseModel):
    """开始阶段时的目标。"""

    title: str = Field(min_length=1, max_length=160)
    objective: str = Field(default="", max_length=10000)


class StageFinishInput(BaseModel):
    """结束阶段的完成项、问题与验证证据。"""

    completed: list[str] = Field(default_factory=list, max_length=100)
    issues: list[str] = Field(default_factory=list, max_length=100)
    verification: list[str] = Field(default_factory=list, max_length=100)
    status: str = "passed"
