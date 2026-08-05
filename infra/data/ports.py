"""数据底座可替换存储端口。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping, Protocol

from .classifier import DataKind


class RuntimeHistoryStore(Protocol):
    """已分类运行记录的持久化与查询能力。"""

    def add(self, kind: DataKind | str, payload: Mapping[str, Any], source: str = "unknown", intersection_id: str | None = None, received_at: str | None = None) -> dict[str, Any]: ...
    def latest(self, kind: DataKind | str) -> dict[str, Any] | None: ...
    def query(self, kind: DataKind | str, limit: int = 100, intersection_id: str | None = None, start_at: str | None = None, end_at: str | None = None) -> list[dict[str, Any]]: ...


class PredictionStore(Protocol):
    """预测历史样本和每日预测结果的读写能力。"""

    def read_history(self, category: str, windows: Iterable[tuple[datetime, datetime]]) -> list[dict[str, Any]]: ...
    def save_daily_predictions(self, category: str, prediction_date: datetime, predictions: dict[str, Any]) -> Any: ...
    def get_current_prediction(self, category: str, current_time: datetime) -> dict[str, Any] | None: ...


class ResultStore(Protocol):
    """最新决策结果的替换与快照查询能力。"""

    def replace(self, results: list[dict[str, Any]]) -> None: ...
    def snapshot(self) -> list[dict[str, Any]]: ...
