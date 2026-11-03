"""数据库连接池开关与借还语义的纯逻辑回归（不依赖可用数据库）。"""

from __future__ import annotations

import psycopg2
import pytest
from psycopg2 import pool as pg_pool

from rag_tech_retriever.platform.record_store import RecordStore, StorageError


def test_pool_disabled_by_default_and_close_is_noop():
    """默认不建池：测试与脚本仍是“一事务一连接”，close 无副作用。"""
    store = RecordStore("qa_pool_default")
    assert store.pool_size == 0
    assert store._connection_pool() is None
    store.close()


def test_pool_size_negative_is_clamped_to_zero():
    """非法负值按 0 处理，避免创建无意义连接池。"""
    store = RecordStore("qa_pool_clamp", pool_size=-3)
    assert store.pool_size == 0


class _ExhaustedPool:
    """只模拟“池已借空”的 getconn，用于验证等待与报错语义。"""

    def __init__(self):
        self.calls = 0

    def getconn(self):
        self.calls += 1
        raise pg_pool.PoolError("connection pool exhausted")


def test_pool_exhaustion_waits_then_reports_busy(monkeypatch):
    """池满时先等待再报“繁忙”，而不是把底层异常直接抛成 5xx。"""
    store = RecordStore("qa_pool_wait", pool_size=2, pool_wait_seconds=0.05)
    fake = _ExhaustedPool()
    monkeypatch.setattr(store, "_connection_pool", lambda: fake)
    with pytest.raises(StorageError, match="连接繁忙"), store.transaction():
        pass
    assert fake.calls >= 2


def test_pool_exhaustion_without_wait_fails_fast(monkeypatch):
    """等待设为 0 时立即报错，便于强制暴露池容量不足。"""
    store = RecordStore("qa_pool_nowait", pool_size=1, pool_wait_seconds=0)
    fake = _ExhaustedPool()
    monkeypatch.setattr(store, "_connection_pool", lambda: fake)
    with pytest.raises(StorageError, match="连接繁忙"), store.transaction():
        pass
    assert fake.calls == 1


class _BrokenConnection:
    """模拟服务器重启后残留的失效连接：借出后一用就报连接级错误。"""

    closed = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, *args, **kwargs):
        raise psycopg2.OperationalError("server closed the connection unexpectedly")


class _BrokenPool:
    def __init__(self):
        self.close_flags: list[bool] = []

    def getconn(self):
        return _BrokenConnection()

    def putconn(self, conn, close=False):
        self.close_flags.append(close)


def test_broken_pooled_connection_is_discarded(monkeypatch):
    """连接级错误必须丢弃连接，不能把坏连接放回池里让后续请求连续失败。"""
    store = RecordStore("qa_pool_broken", pool_size=2)
    fake = _BrokenPool()
    monkeypatch.setattr(store, "_connection_pool", lambda: fake)
    with pytest.raises(StorageError, match="数据库暂不可用"), store.transaction():
        pass
    assert fake.close_flags == [True]
