"""PrivateJson 线程互斥回归：同路径跨实例共享、不同路径互不影响。

背景（2026-11-02）：Windows 的 msvcrt.locking 是进程级字节锁，同进程第二线程
不会阻塞而是直接失败；此前互斥 RLock 每实例各建一把，Windows 下并发双发必有
一路 503「私密资料暂不可写」。修复为按路径共享互斥（弱引用表），文件锁仍负责
跨进程串行。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from rag_tech_retriever.platform.private_json import PrivateJson
from rag_tech_retriever.platform.record_store import StorageError, VersionConflict


def test_same_path_instances_share_one_thread_mutex(tmp_path: Path):
    path = tmp_path / "same.json"
    first, second = PrivateJson(path), PrivateJson(path)
    assert first.mutex is second.mutex  # 跨实例共享，线程互斥才有效


def test_different_paths_use_different_mutexes(tmp_path: Path):
    a, b = PrivateJson(tmp_path / "a.json"), PrivateJson(tmp_path / "b.json")
    assert a.mutex is not b.mutex  # 不同文件互不阻塞（模型调用持锁时不拖累无关路径）


def test_concurrent_same_path_writers_are_serialized(tmp_path: Path):
    path = tmp_path / "concurrent.json"
    errors: list[Exception] = []

    def write(value: int) -> None:
        try:
            file = PrivateJson(path)
            with file.lock():
                current = file.read()
                data = {"count": (current["data"] or {}).get("count", 0) + 1, "by": value}
                file.write_locked(data, current["revision"])
        except (StorageError, VersionConflict, OSError) as exc:  # 记录后统一断言，避免吞错
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["data"]["count"] == 2  # 两次写都成功且串行（无版本冲突、无 503）
