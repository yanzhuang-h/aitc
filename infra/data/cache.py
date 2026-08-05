"""In-memory window cache for recent runtime data."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Deque, Generic, TypeVar

T = TypeVar("T")


class WindowCache(Generic[T]):
    """Keep the latest N records for each key."""

    def __init__(self, max_size: int = 100) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be greater than zero")
        self.max_size = max_size
        self._items: dict[str, Deque[T]] = defaultdict(lambda: deque(maxlen=max_size))

    def append(self, key: str, item: T) -> None:
        self._items[key].append(item)

    def latest(self, key: str) -> T | None:
        items = self._items.get(key)
        if not items:
            return None
        return items[-1]

    def window(self, key: str, limit: int | None = None) -> list[T]:
        items = list(self._items.get(key, ()))
        if limit is None:
            return items
        if limit <= 0:
            return []
        return items[-limit:]

    def clear(self, key: str | None = None) -> None:
        if key is None:
            self._items.clear()
            return
        self._items.pop(key, None)
