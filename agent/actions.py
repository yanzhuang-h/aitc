"""模型可请求的有限动作；配时数值不属于模型输出契约。"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, model_validator

from app.core.models.contract_types import CONTRACT_CONFIG, NonEmptyString
from infra.data.traffic_schemas import ExpertTrafficState, TrafficSource


Reason = Annotated[NonEmptyString, Field(max_length=1000)]
ToolName = Literal[
    "query_traffic_state", "query_history", "query_video_state",
    "query_radar_state", "run_control_policy", "review_signal_plan", "report_anomaly",
]


class EmptyArguments(BaseModel):
    model_config = CONTRACT_CONFIG


class TrafficQueryArguments(BaseModel):
    model_config = CONTRACT_CONFIG

    source: TrafficSource | None = None


class HistoryQueryArguments(BaseModel):
    model_config = CONTRACT_CONFIG

    limit: Annotated[int, Field(ge=1, le=20)] = 3


class ReviewDecision(BaseModel):
    """审查只表达意见、补读来源或回退，不能提交可执行方案。"""

    model_config = CONTRACT_CONFIG

    decision: Literal["ACCEPT", "WARN", "REQUEST_MORE_DATA", "SUGGEST_ADJUSTMENT", "FALLBACK"]
    reason: Reason
    source: Literal["video", "radar"] | None = None
    suggestion: Reason | None = None

    @model_validator(mode="after")
    def check_decision_arguments(self):
        if (self.decision == "REQUEST_MORE_DATA") != (self.source is not None):
            raise ValueError("source is required only for REQUEST_MORE_DATA")
        if (self.decision == "SUGGEST_ADJUSTMENT") != (self.suggestion is not None):
            raise ValueError("suggestion is required only for SUGGEST_ADJUSTMENT")
        return self


class AnomalyArguments(BaseModel):
    model_config = CONTRACT_CONFIG

    kind: Literal["data_missing", "sensor_conflict", "incident", "special_vehicle", "other"]
    reason: Reason


class QueryTrafficStateAction(BaseModel):
    model_config = CONTRACT_CONFIG

    tool: Literal["query_traffic_state"]
    arguments: TrafficQueryArguments


class QueryHistoryAction(BaseModel):
    model_config = CONTRACT_CONFIG

    tool: Literal["query_history"]
    arguments: HistoryQueryArguments


class QueryVideoStateAction(BaseModel):
    model_config = CONTRACT_CONFIG

    tool: Literal["query_video_state"]
    arguments: EmptyArguments


class QueryRadarStateAction(BaseModel):
    model_config = CONTRACT_CONFIG

    tool: Literal["query_radar_state"]
    arguments: EmptyArguments


class RunControlPolicyAction(BaseModel):
    model_config = CONTRACT_CONFIG

    tool: Literal["run_control_policy"]
    arguments: EmptyArguments


class ReviewSignalPlanAction(BaseModel):
    model_config = CONTRACT_CONFIG

    tool: Literal["review_signal_plan"]
    arguments: ReviewDecision


class ReportAnomalyAction(BaseModel):
    model_config = CONTRACT_CONFIG

    tool: Literal["report_anomaly"]
    arguments: AnomalyArguments


ToolAction = Annotated[
    QueryTrafficStateAction | QueryHistoryAction | QueryVideoStateAction |
    QueryRadarStateAction | RunControlPolicyAction | ReviewSignalPlanAction | ReportAnomalyAction,
    Field(discriminator="tool"),
]
ACTION_ADAPTER = TypeAdapter(ToolAction)


class ToolObservation(BaseModel):
    """data 是给模型的摘要；expert_state 只供宿主复用，不能送回提示词。"""

    model_config = CONTRACT_CONFIG

    tool: ToolName
    intersection_id: NonEmptyString
    status: Literal["ok", "unavailable"]
    data: dict[str, Any]
    expert_state: ExpertTrafficState | None = None

    @model_validator(mode="after")
    def check_expert_identity(self):
        if self.expert_state is not None:
            if self.expert_state.observation.cross_id != self.intersection_id:
                raise ValueError("expert_state belongs to another intersection")
            expected = {"query_video_state": "video", "query_radar_state": "radar"}.get(self.tool)
            if expected is not None and self.expert_state.source != expected:
                raise ValueError("expert_state belongs to another source")
        return self
