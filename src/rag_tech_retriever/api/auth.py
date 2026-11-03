"""鉴权逻辑：访问令牌、HMAC 会话 cookie 与 MCP 独立令牌。

本模块由 ``api.main`` 内联逻辑纯搬运而来（M8），规则保持不变：

- 未配置 ``WORKSPACE_ACCESS_TOKEN`` 时视为未启用鉴权（本地开发与回归）；
- Bearer 访问令牌与 ``workspace_session`` 会话 cookie 同为有效凭据；
- MCP 独立令牌只允许 ``/mcp`` 协议入口，禁止访问 ``/api/*``；
- ``/api/session`` 不要求登录，用于读取登录态与提交登录。

抽出的目的：规则可独立单测，``create_app`` 只保留装配。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

from fastapi import Request

SESSION_COOKIE = "workspace_session"


def sign_message(secret: str, message: str) -> str:
    """用工作台令牌对会话载荷做 HMAC-SHA256 签名。"""
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def issue_session(secret: str, lifetime_seconds: int) -> str:
    """生成 ``过期时间:随机数.签名`` 的会话 cookie 值。"""
    message = f"{int(time.time()) + lifetime_seconds}:{secrets.token_hex(16)}"
    return message + "." + sign_message(secret, message)


def verify_session(cookie: str, secret: str) -> bool:
    """校验会话 cookie：签名一致且未过期；格式异常一律视为无效。"""
    if not cookie or not secret:
        return False
    try:
        payload, signature = cookie.rsplit(".", 1)
        expires = int(payload.split(":")[0])
    except (ValueError, IndexError):
        return False
    return expires > time.time() and secrets.compare_digest(
        signature, sign_message(secret, payload)
    )


@dataclass
class LoginThrottle:
    """按客户端地址限制登录失败次数，成功登录清零；内存态，进程重启即清空。

    通用 /api 限流按分钟放行 120 次，对撞库太宽松；账号/令牌登录单独按“失败次数”
    限速，且只在失败时计数，正常使用不会被误伤。
    """

    max_failures: int = 10
    window_seconds: float = 300.0
    _failures: dict[str, list[float]] = field(default_factory=dict)

    def blocked(self, key: str, now: float | None = None) -> int:
        """返回还需等待的秒数；0 表示允许继续尝试。"""
        moment = time.monotonic() if now is None else now
        bucket = self._failures.get(key)
        if not bucket:
            return 0
        recent = [item for item in bucket if moment - item <= self.window_seconds]
        if not recent:
            self._failures.pop(key, None)
            return 0
        self._failures[key] = recent
        if len(recent) >= self.max_failures:
            return max(1, int(self.window_seconds - (moment - recent[0])) + 1)
        return 0

    def fail(self, key: str, now: float | None = None) -> None:
        """记录一次失败；仅保留窗口内的记录，避免无限增长。"""
        moment = time.monotonic() if now is None else now
        bucket = [item for item in self._failures.get(key, []) if moment - item <= self.window_seconds]
        bucket.append(moment)
        self._failures[key] = bucket

    def reset(self, key: str) -> None:
        """登录成功后清空该地址的失败计数。"""
        self._failures.pop(key, None)


@dataclass(frozen=True)
class Authenticator:
    """一次应用装配使用的凭据集合；不读取环境变量，便于测试注入。"""

    secret: str = ""
    mcp_secret: str = ""

    @property
    def enabled(self) -> bool:
        """是否启用了工作台鉴权。"""
        return bool(self.secret)

    def bearer(self, request: Request) -> str:
        """取出 Authorization 的 Bearer 值；非 Bearer 前缀返回空串。"""
        header = request.headers.get("Authorization", "")
        return header[7:] if header.startswith("Bearer ") else ""

    def token_ok(self, token: str) -> bool:
        """常量时间比较访问令牌；未配置令牌时永远不通过。"""
        return bool(self.secret) and secrets.compare_digest(token, self.secret)

    def authenticated(self, request: Request) -> bool:
        """Bearer 令牌或有效会话 cookie 任一成立即视为已登录。"""
        if not self.secret:
            return True
        if self.token_ok(self.bearer(request)):
            return True
        return verify_session(request.cookies.get(SESSION_COOKIE, ""), self.secret)

    def is_mcp_token(self, request: Request) -> bool:
        """请求是否携带 MCP 独立令牌。"""
        return self.token_ok_mcp(self.bearer(request))

    def token_ok_mcp(self, token: str) -> bool:
        """常量时间比较 MCP 独立令牌。"""
        return bool(self.mcp_secret) and secrets.compare_digest(token, self.mcp_secret)


__all__ = [
    "SESSION_COOKIE",
    "Authenticator",
    "LoginThrottle",
    "issue_session",
    "sign_message",
    "verify_session",
]
