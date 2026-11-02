"""统一错误码与业务异常：所有可预期错误都有稳定 code，禁止裸 except 与堆栈泄露。

HTTP 层映射由 api.main 的异常处理器承担；本模块提供：
- ErrorCode 常量表（日志/前端可依赖的稳定标识）
- AppError 基类（code + http_status + 用户可读 message，不含内部细节）
- error_payload()：统一错误信封 {detail, code, request_id}
"""

from __future__ import annotations


class ErrorCode:
    """稳定错误码：新增只追加不复用，前端与日志据此归因。"""

    VALIDATION = "VALIDATION_ERROR"  # 入参不合法（HTTP 400/422）
    NOT_FOUND = "NOT_FOUND"  # 目标记录不存在（HTTP 404）
    VERSION_CONFLICT = "VERSION_CONFLICT"  # 乐观锁冲突（HTTP 409）
    RATE_LIMITED = "RATE_LIMITED"  # 触发限流（HTTP 429）
    STORAGE = "STORAGE_UNAVAILABLE"  # 存储不可用（HTTP 503）
    TOOL = "TOOL_FAILURE"  # 工具调用失败（HTTP 503）
    UNAUTHORIZED = "UNAUTHORIZED"  # 未携带或携带无效令牌（HTTP 401）
    FORBIDDEN = "FORBIDDEN"  # 跨站写入等拒绝（HTTP 403）
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"  # 提交内容超限（HTTP 413）
    INTERNAL = "INTERNAL"  # 未预期的服务端错误（HTTP 500）


def error_payload(message: str, code: str, request_id: str = "") -> dict:
    """统一错误信封：detail 面向用户，code 稳定归因，request_id 供日志关联。"""
    return {"detail": message, "code": code, "request_id": request_id}


class AppError(Exception):
    """带稳定错误码的业务异常基类；message 面向用户，不携带内部细节。"""

    code = ErrorCode.VALIDATION
    http_status = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def payload(self, request_id: str = "") -> dict:
        return error_payload(self.message, self.code, request_id)


class ValidationError(AppError):
    """入参/业务规则不合法。"""

    code = ErrorCode.VALIDATION
    http_status = 400


class NotFoundError(AppError):
    """目标记录不存在。"""

    code = ErrorCode.NOT_FOUND
    http_status = 404


class ConflictError(AppError):
    """乐观锁版本冲突。"""

    code = ErrorCode.VERSION_CONFLICT
    http_status = 409


class PayloadTooLargeError(AppError):
    """提交内容超过大小限制。"""

    code = ErrorCode.PAYLOAD_TOO_LARGE
    http_status = 413


class UnauthorizedError(AppError):
    """未携带或携带无效令牌。"""

    code = ErrorCode.UNAUTHORIZED
    http_status = 401


class ForbiddenError(AppError):
    """跨站写入等安全策略拒绝。"""

    code = ErrorCode.FORBIDDEN
    http_status = 403


class RateLimitedError(AppError):
    code = ErrorCode.RATE_LIMITED
    http_status = 429


class StorageUnavailableError(AppError):
    code = ErrorCode.STORAGE
    http_status = 503


class ToolFailureError(AppError):
    code = ErrorCode.TOOL
    http_status = 503


class InternalError(AppError):
    code = ErrorCode.INTERNAL
    http_status = 500
