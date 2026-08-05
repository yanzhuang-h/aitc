"""运行期窗口缓存，保持与旧服务的数据窗口一致。"""

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
    timestamp: float
    data: dict[str, Any]

    def legacy_tuple(self) -> tuple[float, dict[str, Any]]:
        return self.timestamp, self.data


class RuntimeDataCache:
    """按数据类型维护内存窗口。

    该组件刻意复刻当前 `Server_AITC.py` 的窗口行为，先迁移数据职责，
    算法输入形态保持不变。
    """

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
        if kind not in self.windows:
            return
        now = time.time() if timestamp is None else timestamp
        with self._lock:
            self._items[kind].append(WindowItem(now, data))
            self._clear_expired_locked(kind, now)

    def clear_expired(self, kind: DataKind | None = None) -> None:
        now = time.time()
        with self._lock:
            if kind is None:
                for current_kind in self._items:
                    self._clear_expired_locked(current_kind, now)
                return
            self._clear_expired_locked(kind, now)

    def recent_data(self, kind: DataKind) -> list[dict[str, Any]]:
        self.clear_expired(kind)
        with self._lock:
            return [item.data for item in self._items.get(kind, ())]

    def recent_legacy_tuples(self, kind: DataKind) -> list[tuple[float, dict[str, Any]]]:
        self.clear_expired(kind)
        with self._lock:
            return [item.legacy_tuple() for item in self._items.get(kind, ())]

    def duration_data(self, kind: DataKind, duration_seconds: int) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            return [
                item.data
                for item in self._items.get(kind, ())
                if now - item.timestamp < duration_seconds
            ]

    def size(self, kind: DataKind) -> int:
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
