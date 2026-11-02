"""LRU+TTL 缓存中间件：检索结果、工具解析结果复用。

functools.lru_cache 无过期语义，这里实现带 TTL 的有界缓存：
maxsize 淘汰最久未用，ttl 到期视为未命中。线程安全（锁内操作）。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


class TTLCache:
    """有界缓存：get/put/清空；过期与容量淘汰都在访问时惰性执行。"""

    def __init__(self, maxsize: int = 128, ttl_seconds: float = 60.0) -> None:
        if maxsize < 1:
            raise ValueError("maxsize 必须 >= 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须 > 0")
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        """命中返回缓存值并提升为最近使用；未命中/过期返回 None。"""
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return None
            stored_at, value = item
            if time.monotonic() - stored_at > self._ttl:
                del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return value

    def put(self, key: str, value: Any) -> None:
        """写入并淘汰最久未用项；value 为 None 视为删除该键。"""
        with self._lock:
            if value is None:
                self._data.pop(key, None)
                return
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def cached(self, fn: Callable[..., Any], key_fn: Callable[..., str] | None = None) -> Callable[..., Any]:
        """包装函数：按 key_fn(args) 缓存结果；未命中时调用原函数。"""

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = key_fn(*args, **kwargs) if key_fn else repr((args, sorted(kwargs.items())))
            hit = self.get(key)
            if hit is not None:
                return hit
            value = fn(*args, **kwargs)
            self.put(key, value)
            return value

        return wrapper

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
