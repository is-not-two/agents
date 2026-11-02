"""Bounded single-attempt model transport and invocation-local generation policy."""

import http.client
import ipaddress
import json
import urllib.error
import urllib.request
from contextvars import ContextVar
from urllib.parse import urlsplit

MAX_PROVIDER_RESPONSE_BYTES = 1048576
DEFAULT_CONTEXT_CHARS = 120000
GENERATION_POLICY: ContextVar[dict | None] = ContextVar("generation_policy", default=None)


class ProviderError(RuntimeError):
    """Safe error text only; never expose provider bodies, keys or submitted data."""

    def __init__(self, message: str, code: str = "transport", status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def usage_metadata(raw: object) -> dict:
    """Report only supplied integer counts; unknown is not a free model call."""
    raw = raw if isinstance(raw, dict) else {}
    return {key: value if type(value := raw.get(key)) is int and value >= 0 else None
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")}


def validate_provider_url(base: str) -> str:
    """Require verified HTTPS except literal loopback/local test endpoints."""
    try:
        if not isinstance(base, str) or any(char.isspace() for char in base):
            raise ValueError
        parts = urlsplit(base)
        if (not parts.hostname or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment):
            raise ValueError
        _ = parts.port
        loopback = parts.hostname == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(parts.hostname).is_loopback
        except ValueError:
            pass
        if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
            raise ValueError
    except ValueError as exc:
        raise ProviderError("模型连接必须使用HTTPS；明文HTTP仅允许本机回环测试，未发起请求", "insecure") from exc
    return base.rstrip("/")


def post_chat(config: dict, body: dict, timeout: int, max_chars: int,
              max_response_bytes: int = MAX_PROVIDER_RESPONSE_BYTES) -> dict:
    """One bounded request, normal CA verification, no redirect and no auto retry."""
    base = validate_provider_url(config.get("base_url", ""))
    if not isinstance(config.get("api_key"), str) or not config["api_key"]:
        raise ProviderError("尚未配置模型连接，未发起请求")
    raw = json.dumps(body, ensure_ascii=False)
    if len(raw) > max_chars:
        raise ProviderError("上下文超过配置限制，未发起模型请求", "context_limit")
    try:
        request = urllib.request.Request(base + "/chat/completions", raw.encode("utf-8"),
            {"Content-Type": "application/json", "Authorization": "Bearer " + config["api_key"]})
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            data = response.read(max_response_bytes + 1)
        if len(data) > max_response_bytes:
            raise ValueError
        result = json.loads(data)
        if not isinstance(result, dict):
            raise TypeError
        return result
    except urllib.error.HTTPError as exc:
        raise ProviderError("模型服务返回错误，本次没有自动重试", status=exc.code) from exc
    except (OSError, http.client.HTTPException, ValueError, TypeError) as exc:
        raise ProviderError("模型未成功返回有效响应，本次没有自动重试") from exc
