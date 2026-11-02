"""有界私密 JSON 文件：跨进程锁、原子替换、内容版本与无密钥日志。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import weakref
from contextlib import contextmanager
from pathlib import Path

from rag_tech_retriever.platform.record_store import StorageError, VersionConflict


class _MutexHolder:
    """可弱引用的线程互斥持有器（_thread.RLock 本身不支持弱引用）。"""

    __slots__ = ("__weakref__", "lock")

    def __init__(self) -> None:
        self.lock = threading.RLock()


class PrivateJson:
    """不属于公共备份，调用方须明确说明需要单独保护和恢复。"""

    # 同一路径的线程互斥必须跨实例共享：Windows 的 msvcrt.locking 是进程级字节锁，
    # 同进程第二线程不会阻塞而是直接失败（fcntl.flock 在 Linux 会阻塞，掩盖了该缺陷）。
    # 若互斥锁每实例各建一把，Windows 下并发双发必有一路拿到 503（2026-11-02 实测修复）。
    # 用弱引用表：实例全部释放后条目自动回收，长驻进程不会随分析次数无限增长。
    _path_mutexes: weakref.WeakValueDictionary[str, _MutexHolder] = weakref.WeakValueDictionary()
    _registry_lock = threading.Lock()

    def __init__(self, path: Path, max_bytes: int = 1048576, allow_plain: bool = False) -> None:
        self.path, self.max_bytes = path, max_bytes
        self.allow_plain = allow_plain
        key = os.path.abspath(os.fspath(path))
        with PrivateJson._registry_lock:
            holder = PrivateJson._path_mutexes.get(key)
            if holder is None:
                holder = _MutexHolder()
                PrivateJson._path_mutexes[key] = holder
        self._mutex_holder = holder  # 持有强引用：与本实例同寿，保住弱表条目
        self.mutex = holder.lock

    @contextmanager
    def lock(self):
        """锁文件不随正文原子替换，线程和进程串行使用相同锁路径。"""
        try:
            with self.mutex:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.is_symlink() or self.path.with_suffix(".lock").is_symlink():
                    raise StorageError("私密文件不能使用符号链接")
                with self.path.with_suffix(".lock").open("a+b") as file:
                    if file.seek(0, 2) == 0:
                        file.write(b"0")
                        file.flush()
                    file.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(file, fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        file.seek(0)
                        if os.name == "nt":
                            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            fcntl.flock(file, fcntl.LOCK_UN)
        except OSError as exc:
            raise StorageError("私密资料暂不可写，请检查目录权限或稍后重试") from exc

    @staticmethod
    def revision(data: dict) -> str:
        """内容指纹不包含文件时间或供应商密钥。"""
        return hashlib.sha256(
            json.dumps(
                data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()

    def read(self) -> dict:
        """损坏文件不回退为空资料，以免下次保存覆盖用户内容。"""
        if self.path.is_symlink():
            raise StorageError("私密文件不能使用符号链接")
        if not self.path.exists():
            return {"revision": "missing", "data": None}
        try:
            if self.path.is_symlink() or self.path.stat().st_size > self.max_bytes:
                raise ValueError
            with self.path.open("rb") as file:
                raw = file.read(self.max_bytes + 1)
            if len(raw) > self.max_bytes:
                raise ValueError

            def unique(pairs):
                result = {}
                for key, item in pairs:
                    if key in result:
                        raise ValueError("Duplicate JSON key")
                    result[key] = item
                return result

            value = json.loads(raw, object_pairs_hook=unique)
            if (
                self.allow_plain
                and isinstance(value, dict)
                and "data" not in value
                and "revision" not in value
            ):
                return {"revision": "legacy-" + self.revision(value), "data": value}
            if (
                not isinstance(value, dict)
                or set(value) != {"revision", "data"}
                or not isinstance(value["data"], dict)
                or value["revision"] != self.revision(value["data"])
            ):
                raise ValueError
            return value
        except (OSError, ValueError, TypeError) as exc:
            raise StorageError("私密资料文件损坏或不可读，未按空资料覆盖") from exc

    def write_locked(self, data: dict, expected: str) -> dict:
        """调用方持有本文件锁，先比较版本，再原子替换，出错保留旧文件。"""
        if self.read()["revision"] != expected:
            raise VersionConflict("资料已更新，请保留本次输入并重新读取最新版本")
        value = {"revision": self.revision(data), "data": data}
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
        if len(raw) > self.max_bytes:
            raise StorageError("私密资料超过文件大小限制，原文件未替换")
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix=".private-", dir=self.path.parent)
            with os.fdopen(descriptor, "wb") as file:
                file.write(raw)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
            return value
        except OSError as exc:
            raise StorageError("私密资料保存失败，未返回成功") from exc
        finally:
            if temporary and Path(temporary).is_file():
                Path(temporary).unlink()

    def save(self, data: dict, expected: str) -> dict:
        """单次 CAS 事务，不进行模型或网络请求。"""
        with self.lock():
            return self.write_locked(data, expected)
