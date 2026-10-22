"""V2 交通边界契约，复用现有分类和单路口状态字段。"""

from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic.dataclasses import dataclass

from app.core.models.contract_types import (
    CONTRACT_CONFIG, FiniteNumber, NonEmptyString, Timestamp,
)
from lib.control_functions.types import IntersectionControlRequest

from .classifier import DataKind, DataSource

TrafficSource = Literal["video", "radar", "internet", "ev"]


class RawTrafficEvent(BaseModel):
    """严格校验事件信封；原始异构报文和已有质量问题均保留。"""

    model_config = CONTRACT_CONFIG

    kind: DataKind
    source: DataSource
    received_at: Timestamp
    intersection_id: NonEmptyString | None = None
    payload: dict[str, Any]
    quality_issues: list[NonEmptyString] = Field(default_factory=list)


@dataclass(config=CONTRACT_CONFIG)
class TrafficSnapshot(IntersectionControlRequest):
    """单路口一轮算法上下文，继承十五个真实字段而不另建一套状态。"""

    cross_id: NonEmptyString
    current_time: Timestamp

    @property
    def intersection_id(self) -> str:
        return self.cross_id


class ExpertTrafficState(BaseModel):
    """专家只能提供状态和质量信息，不能携带配时方案。"""

    model_config = CONTRACT_CONFIG

    source: TrafficSource
    observation: TrafficSnapshot
    missing_fields: list[NonEmptyString] = Field(default_factory=list)
    confidence: FiniteNumber = Field(ge=0, le=1)


class TrafficDataView(BaseModel):
    """按路口和来源读取的当前窗口；snapshot 始终是完整算法上下文。"""

    model_config = CONTRACT_CONFIG

    intersection_id: NonEmptyString | None
    source: TrafficSource | None = None
    transport: DataSource | None = None
    events: list[RawTrafficEvent] = Field(default_factory=list)
    snapshot: TrafficSnapshot | None = None
    missing_fields: list[NonEmptyString] = Field(default_factory=list)
    quality_issues: list[NonEmptyString] = Field(default_factory=list)
    truncated: bool = False
