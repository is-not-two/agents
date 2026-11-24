"""Gzip negotiation that respects explicit client opt-out and wildcard weights."""
from math import isfinite

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Receive, Scope, Send


def accepts_gzip(value: str) -> bool:
    """Explicit gzip weights override wildcard; malformed weights fail closed."""
    weights: dict[str, float] = {}
    for item in value.lower().split(","):
        parts = item.strip().split(";")
        quality = 1.0
        for parameter in parts[1:]:
            name, separator, raw = parameter.strip().partition("=")
            if name.strip() == "q":
                try:
                    quality = float(raw) if separator else 0.0
                except ValueError:
                    quality = 0.0
                if not isfinite(quality) or not 0 <= quality <= 1:
                    quality = 0.0
        name = parts[0].strip()
        weights[name] = min(weights.get(name, 1.0), quality)
    return weights.get("gzip", weights.get("*", 0.0)) > 0


class NegotiatedGZipMiddleware(GZipMiddleware):
    """Normalize gzip negotiation before Starlette's substring-based dispatch."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = scope.get("headers", [])
            value = ",".join(v.decode("latin-1") for k, v in headers if k.lower() == b"accept-encoding")
            # Starlette still owns compression, Vary, streaming and SSE handling.
            normalized = b"gzip" if accepts_gzip(value) else b"identity"
            scope = {**scope, "headers": [(k, v) for k, v in headers if k.lower() != b"accept-encoding"] + [(b"accept-encoding", normalized)]}
        await super().__call__(scope, receive, send)
