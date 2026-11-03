"""请求体大小守卫：按块计数读取，避免超限请求整包进内存（M6）。

``protect`` 中间件原先用 ``await request.body()`` 整包读入再比大小；
32MB 导入会先占满内存才拒绝。本模块优先信任 ``Content-Length``，
未知长度（chunked）时按块累计，超限立刻返回失败。

读取完成后把已消费的内容写回 ``request._body``（Starlette 的标准缓存位），
下游 handler / multipart 解析仍可正常读取，不是“读取即消费”。
"""

from __future__ import annotations

from fastapi import Request


async def body_within_limit(request: Request, limit: int) -> bool:
    """在不超过 ``limit`` 的前提下缓存请求体；超限返回 False 且不再继续读取。

    调用方须确保本函数是首个读取请求体的位置（本项目 protect 为最外层中间件）。
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        # 已知超限：不读取正文，直接拒绝。
        return False

    cached = getattr(request, "_body", None)
    if cached is not None:
        return len(cached) <= limit

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return False
        chunks.append(chunk)
    request._body = b"".join(chunks)
    return True


__all__ = ["body_within_limit"]
