"""Resolve a member quota key for public reads; never use this for authorization."""
from __future__ import annotations

import hashlib
import re
from time import perf_counter
from collections.abc import Callable


def public_read_member(transaction: Callable, token: str, *,
                       observe: Callable[[dict[str, float]], None] | None = None) -> str | None:
    """Only a live database session earns a member bucket, not a cookie value."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    started = perf_counter() if observe else 0.0
    with transaction() as cur:
        acquired = perf_counter() if observe else 0.0
        cur.execute(
            "SELECT member_id FROM community.sessions "
            "WHERE token_digest=%s AND expires_at>now()",
            (hashlib.sha256(token.encode("ascii")).digest(),),
        )
        row = cur.fetchone()
        queried = perf_counter() if observe else 0.0
    if observe:
        observe({"enter_ms": (acquired-started)*1000, "query_ms": (queried-acquired)*1000,
                 "exit_ms": (perf_counter()-queried)*1000})
    return str(row["member_id"]) if row else None
