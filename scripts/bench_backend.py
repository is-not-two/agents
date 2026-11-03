"""后端性能基准：M5 状态接口 p95 与 M6 请求体内存峰值。

只在隔离回归库（POSTGRES_DB=regression）且存在 SHILIE_QA_RUN_ID 时运行，
避免误连正式库。结果写入 ``output/ci/benchmarks/backend.json``，供验收引用。

M5：写入 1,000 条知识 + 500 个规划节点，测量 ``GET /api/status`` 的 p95。
M6：对比旧式 ``request.body()`` 与新守卫在 64MB / 32MB 上限下的 tracemalloc 峰值。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import statistics
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.testclient import TestClient

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.platform.record_store import RecordStore

KNOWLEDGE_COUNT = 1000
PLAN_RECORDS = 50
NODES_PER_PLAN = 10
BODY_BYTES = 64 * 1024 * 1024
BODY_LIMIT = 32 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


def _require_isolated_database() -> str:
    """拒绝在非回归库或缺少运行标识时执行写入型基准。"""
    db = os.environ.get("POSTGRES_DB", "")
    run_id = os.environ.get("SHILIE_QA_RUN_ID", "")
    if db != "regression":
        raise SystemExit("基准只允许在 POSTGRES_DB=regression 的隔离库运行")
    if not re.fullmatch(r"[0-9a-f]{12}", run_id):
        raise SystemExit("缺少合法的 SHILIE_QA_RUN_ID（12 位十六进制）")
    return run_id


def _seed(store: RecordStore) -> None:
    """批量写入知识记录与规划节点，覆盖状态接口的计数与 JSONB 展开路径。"""
    store.ensure_schema()
    knowledge = [
        {
            "kind": "knowledge",
            "data": {"title": f"基准知识 {index}", "body": "用于状态接口计数", "tags": ["bench"]},
        }
        for index in range(KNOWLEDGE_COUNT)
    ]
    for batch_start in range(0, len(knowledge), 200):
        store.save_batch(knowledge[batch_start:batch_start + 200])
    plans = []
    for index in range(PLAN_RECORDS):
        nodes = [
            {"id": f"n{index}-{node}", "title": f"节点 {node}", "done": (node + index) % 2 == 0}
            for node in range(NODES_PER_PLAN)
        ]
        plans.append({"kind": "plan", "data": {"title": f"基准规划 {index}", "acts": [{"nodes": nodes}]}})
    store.save_batch(plans)


def _cleanup(store: RecordStore) -> None:
    """只删除本次基准创建的表，不触碰共享回归表。"""
    with store.transaction() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {store.versions}, {store.records}")


def _percentile(samples: list[float], ratio: float) -> float:
    ordered = sorted(samples)
    index = max(0, math.ceil(ratio * len(ordered)) - 1)
    return ordered[index]


def bench_status(store: RecordStore) -> dict[str, Any]:
    """测量状态接口的稳态延迟，并与 200ms 验收线比较。"""
    app = create_app(store=store, token="")
    client = TestClient(app)
    for _ in range(5):
        client.get("/api/status")
    samples = []
    for _ in range(30):
        started = time.perf_counter()
        response = client.get("/api/status")
        samples.append((time.perf_counter() - started) * 1000)
        if response.status_code != 200:
            raise SystemExit(f"状态接口返回 {response.status_code}")
    return {
        "samples": len(samples),
        "p50_ms": round(statistics.median(samples), 2),
        "p95_ms": round(_percentile(samples, 0.95), 2),
        "max_ms": round(max(samples), 2),
        "threshold_ms": 200,
        "passed": _percentile(samples, 0.95) < 200,
    }


def _request(total: int, *, declared: bool) -> Request:
    """构造按块产出的 ASGI 请求；declared 模拟已知 Content-Length 的超限导入。"""
    sent = 0

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent >= total:
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = b"x" * min(CHUNK_BYTES, total - sent)
        sent += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": sent < total}

    headers = [(b"content-length", str(total).encode())] if declared else []
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/import",
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope, receive)


def _peak(operation: Callable[[], Awaitable[Any]]) -> int:
    """在独立 tracemalloc 会话中执行异步操作并返回峰值字节数。"""
    async def run() -> Any:
        return await operation()

    tracemalloc.start()
    try:
        asyncio.run(run())
        _, peak = tracemalloc.get_traced_memory()
        return peak
    finally:
        tracemalloc.stop()


def bench_body() -> dict[str, Any]:
    """对比整包读取与新守卫的内存峰值；新实现只接受未超限正文。"""
    from rag_tech_retriever.api.request_guard import body_within_limit

    baseline_peak = _peak(lambda: _request(BODY_BYTES, declared=False).body())
    declared_peak = _peak(lambda: body_within_limit(_request(BODY_BYTES, declared=True), BODY_LIMIT))
    chunked_peak = _peak(lambda: body_within_limit(_request(BODY_BYTES, declared=False), BODY_LIMIT))
    return {
        "body_bytes": BODY_BYTES,
        "limit_bytes": BODY_LIMIT,
        "baseline_peak_bytes": baseline_peak,
        "declared_peak_bytes": declared_peak,
        "chunked_peak_bytes": chunked_peak,
        "declared_ratio": round(declared_peak / max(1, baseline_peak), 4),
        "chunked_ratio": round(chunked_peak / max(1, baseline_peak), 4),
        "passed": declared_peak < BODY_LIMIT and chunked_peak < baseline_peak,
    }


def main() -> None:
    """运行两项基准并落盘 JSON；任一未达标时以非零码退出。"""
    parser = argparse.ArgumentParser(description="后端 M5/M6 基准")
    parser.add_argument("--output", default="output/ci/benchmarks/backend.json")
    args = parser.parse_args()
    run_id = _require_isolated_database()
    store = RecordStore(prefix=f"bench_{run_id}", config=ConfigLoader.load_default())
    result: dict[str, Any] = {"run_id": run_id, "database": os.environ.get("POSTGRES_DB")}
    try:
        _seed(store)
        result["status"] = bench_status(store)
    finally:
        _cleanup(store)
    result["body"] = bench_body()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if not result["status"]["passed"] or not result["body"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
