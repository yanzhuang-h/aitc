"""将预测算法与预测数据仓库组合为运行期服务。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Protocol


class PredictionStore(Protocol):
    """预测服务实际依赖的最小持久化能力。"""

    def read_history(
        self,
        category: str,
        windows: Iterable[tuple[datetime, datetime]],
    ) -> list[dict[str, Any]]: ...

    def save_daily_predictions(
        self,
        category: str,
        prediction_date: datetime,
        predictions: dict[str, Any],
    ) -> Any: ...

    def get_current_prediction(
        self,
        category: str,
        current_time: datetime,
    ) -> dict[str, Any] | None: ...


class FlowPredictionService:
    """为流量预测算法注入历史与结果仓库。"""

    def __init__(self, algorithm: Any, repository: PredictionStore) -> None:
        self.algorithm = algorithm
        self.repository = repository

    def flow_pre_json_Gen(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.algorithm.flow_pre_json_Gen(*args, **kwargs)

    def get_current_flow_prediction(self):
        return self.algorithm.get_current_flow_prediction(repository=self.repository)

    def daily_prediction_job(self) -> None:
        self.algorithm.daily_prediction_job(repository=self.repository)


class QueuePredictionService:
    """为排队预测算法注入历史与结果仓库。"""

    def __init__(self, algorithm: Any, repository: PredictionStore) -> None:
        self.algorithm = algorithm
        self.repository = repository

    def queue_pre_json_gen(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.algorithm.queue_pre_json_gen(*args, **kwargs)

    def get_current_queue_prediction(self):
        return self.algorithm.get_current_queue_prediction(repository=self.repository)

    def daily_queue_prediction(self) -> None:
        self.algorithm.daily_queue_prediction(repository=self.repository)
