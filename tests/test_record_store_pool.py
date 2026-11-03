"""数据库连接池开关的纯逻辑回归（不依赖可用数据库）。"""

from __future__ import annotations

from rag_tech_retriever.platform.record_store import RecordStore


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
