"""短期记忆仓库。

短期记忆只负责保存最近一段时间的运行数据，不绑定 Redis、内存或其他
具体技术。当前实现使用线程安全的内存窗口，后续可以替换窗口存储实现。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
import time
from typing import Any, Deque

from .classifier import DataKind


DEFAULT_WINDOW_SECONDS: dict[DataKind, int] = {
    DataKind.FLOW: 600,
    DataKind.QUEUE: 240,
    DataKind.STAGE: 600,
    DataKind.EXTEND: 600,
    DataKind.ONLINE: 1800,
    DataKind.LATEST: 1800,
    DataKind.RADAR: 600,
    DataKind.BOYAN: 600,
}


@dataclass(slots=True)
class WindowItem:
    """短期记忆中的一条带时间数据。"""

    timestamp: float
    data: dict[str, Any]

    def legacy_tuple(self) -> tuple[float, dict[str, Any]]:
        return self.timestamp, self.data


class ShortTermMemory:
    """按数据类型维护实时运行窗口。"""

    def __init__(self, windows: dict[DataKind, int] | None = None) -> None:
        self.windows = dict(DEFAULT_WINDOW_SECONDS)
        if windows:
            self.windows.update(windows)
        self._items: dict[DataKind, Deque[WindowItem]] = {
            kind: deque() for kind in self.windows
        }
        self._lock = threading.Lock()

    def add(
        self,
        kind: DataKind,
        data: dict[str, Any],
        timestamp: float | None = None,
    ) -> None:
        """写入一条实时数据，并清理当前类型的过期数据。"""
        if kind not in self.windows:
            return
        now = time.time() if timestamp is None else timestamp
        with self._lock:
            self._items[kind].append(WindowItem(now, data))
            self._clear_expired_locked(kind, now)

    def clear_expired(self, kind: DataKind | None = None) -> None:
        """清理指定类型或全部类型的过期数据。"""
        now = time.time()
        with self._lock:
            if kind is None:
                for current_kind in self._items:
                    self._clear_expired_locked(current_kind, now)
                return
            self._clear_expired_locked(kind, now)

    def recent_data(self, kind: DataKind) -> list[dict[str, Any]]:
        """读取指定类型的当前窗口快照。"""
        self.clear_expired(kind)
        with self._lock:
            return [item.data for item in self._items.get(kind, ())]

    def recent_legacy_tuples(self, kind: DataKind) -> list[tuple[float, dict[str, Any]]]:
        """返回旧算法使用的 ``(timestamp, data)`` 结构。"""
        self.clear_expired(kind)
        with self._lock:
            return [item.legacy_tuple() for item in self._items.get(kind, ())]

    def duration_data(self, kind: DataKind, duration_seconds: int) -> list[dict[str, Any]]:
        """读取指定时长内的数据，不改变仓库配置的窗口时长。"""
        now = time.time()
        with self._lock:
            return [
                item.data
                for item in self._items.get(kind, ())
                if now - item.timestamp < duration_seconds
            ]

    def size(self, kind: DataKind) -> int:
        """返回指定类型当前窗口中的有效数据量。"""
        self.clear_expired(kind)
        with self._lock:
            return len(self._items.get(kind, ()))

    def _clear_expired_locked(self, kind: DataKind, now: float) -> None:
        max_age = self.windows.get(kind)
        if max_age is None:
            return
        items = self._items.get(kind)
        if items is None:
            return
        while items and now - items[0].timestamp > max_age:
            items.popleft()
