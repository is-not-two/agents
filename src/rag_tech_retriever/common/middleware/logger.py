"""结构化日志中间件：JSON 行格式输出，全链路复用。

只依赖标准库 logging；输出单行 JSON，中文不转义。
请求级访问日志由 tracer 中间件写入本 logger（见 tracer.py）。
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    """把 LogRecord 序列化为一行 JSON；extra 字段收进顶层。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("shilie")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """返回 shilie.<name> logger；首次调用时完成 JSON handler 装配。"""
    _configure()
    return logging.getLogger(f"shilie.{name}")


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """以附加字段形式输出一条结构化事件日志。"""
    logger.info(event, extra={"fields": fields})
