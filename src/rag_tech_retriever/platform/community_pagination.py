"""Opaque ordering cursors, not authorization tokens; queries must scope ownership."""
import base64
import binascii
import json
from datetime import datetime, timezone
from uuid import UUID


def encode_cursor(kind: str, row: dict) -> str:
    """Preserve the timestamp/UUID tie-breaker even if the boundary row disappears."""
    payload = [1, kind, row["created_at"].astimezone(timezone.utc).isoformat(), str(row["id"])]
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_cursor(value: str | None, kind: str) -> tuple[datetime, str] | None:
    """Validate shape and endpoint scope; do not trust a cursor to grant access."""
    if value is None:
        return None
    try:
        if not value or len(value) > 256:
            raise ValueError("cursor size")
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if not isinstance(payload, list) or len(payload) != 4:
            raise ValueError("cursor shape")
        version, scope, timestamp, identifier = payload
        if type(version) is not int or version != 1 or scope != kind:
            raise ValueError("cursor version/scope")
        if not isinstance(timestamp, str) or not isinstance(identifier, str):
            raise ValueError("cursor fields")  # noqa: TRY004 - 光标非法统一用 ValueError
        date = datetime.fromisoformat(timestamp)
        if date.tzinfo is None or date.utcoffset() is None:
            raise ValueError("cursor timestamp needs timezone")
        return date.astimezone(timezone.utc), str(UUID(identifier))
    except (ValueError, TypeError, binascii.Error, UnicodeError, OverflowError) as error:
        raise ValueError("invalid pagination cursor") from error


def page_result(rows: list[dict], size: int, kind: str) -> dict:
    """One lookahead row detects a next page without a full count query."""
    items = rows[:size]
    return {"items": items, "next": encode_cursor(kind, items[-1]) if len(rows) > size else None}
