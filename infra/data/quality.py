"""运行数据质量的非阻断式监控。"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from .classifier import DataKind, DataSource


class DataQualityMonitor:
    """汇总契约问题，不影响运行数据的接收与处理。"""

    def __init__(self, recent_limit: int = 100) -> None:
        self._lock = Lock()
        self._total = 0
        self._by_kind: dict[str, int] = {}
        self._recent: deque[dict[str, Any]] = deque(maxlen=recent_limit)

    def record(self, kind: DataKind, source: DataSource, issues: list[str]) -> None:
        if not issues:
            return
        item = {"kind": kind.value, "source": source.value, "issues": list(issues), "recorded_at": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            self._total += 1
            self._by_kind[kind.value] = self._by_kind.get(kind.value, 0) + 1
            self._recent.append(item)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"total_issues": self._total, "issues_by_kind": dict(self._by_kind), "recent_issues": list(self._recent)}
