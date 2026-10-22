"""每路口每轮一条结构化记录；日志只观察决策，不改写业务数据。"""

from contextlib import contextmanager
from dataclasses import fields, is_dataclass
import json
import math
import sys
from time import perf_counter_ns
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, PrivateAttr

from control.adapters import signal_plan_from_legacy
from control.schemas import SignalPlan
from app.core.models.contract_types import CONTRACT_CONFIG, FiniteNumber, NonEmptyString


def trace_value(value: Any, *, path: str = "$", seen: set[int] | None = None, depth: int = 0) -> Any:
    """完整保留普通 JSON 数据；异常对象显式标记，避免调用其 repr 或修改原对象。"""
    if isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > 13000:
        return {"trace_omitted": "oversized_integer", "path": path}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"trace_omitted": "non_finite_number", "path": path}
    if depth >= 32:
        return {"trace_omitted": "depth_limit", "path": path}
    seen = set() if seen is None else seen
    if id(value) in seen:
        return {"trace_omitted": "cycle", "path": path}
    identity = id(value)
    seen.add(identity)
    try:
        if isinstance(value, (DecisionTrace, TraceError, SignalPlan)):
            value = {key: getattr(value, key) for key in type(value).model_fields}
        elif is_dataclass(value) and not isinstance(value, type):
            value = {field.name: getattr(value, field.name) for field in fields(value)}
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if not isinstance(key, (str, int, float, bool, type(None))):
                    return {"trace_omitted": "unsupported_mapping_key", "path": path}
                if isinstance(key, float) and not math.isfinite(key):
                    return {"trace_omitted": "non_finite_mapping_key", "path": path}
                if isinstance(key, int) and key.bit_length() > 13000:
                    return {"trace_omitted": "oversized_mapping_key", "path": path}
                normalized = key if isinstance(key, str) else json.dumps(key, allow_nan=False)
                if normalized in result:
                    return {"trace_omitted": "mapping_key_collision", "path": path}
                result[normalized] = trace_value(item, path=f"{path}.{normalized}", seen=seen, depth=depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [trace_value(item, path=f"{path}[{index}]", seen=seen, depth=depth + 1)
                    for index, item in enumerate(value)]
        return {"trace_omitted": "unsupported_type", "type": type(value).__name__, "path": path}
    finally:
        seen.remove(identity)


class TraceError(BaseModel):
    model_config = CONTRACT_CONFIG
    stage: NonEmptyString
    type: NonEmptyString
    message: str


class DecisionTrace(BaseModel):
    model_config = CONTRACT_CONFIG

    event: Literal["aitc.decision"] = "aitc.decision"
    schema_version: Literal[1] = 1
    trace_id: NonEmptyString = Field(default_factory=lambda: uuid4().hex)
    batch_id: NonEmptyString
    intersection_id: NonEmptyString
    input_timestamp: FiniteNumber | None = None
    snapshot_status: Literal["not_captured", "captured", "unavailable"] = "not_captured"
    traffic_snapshot: dict[str, Any] | None = None
    input_request: dict[str, Any] | None = None
    control_policy: NonEmptyString
    route: list[str] = Field(default_factory=list)
    expert_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    llm_participated: bool | None = False
    model_calls: int | None = Field(default=0, ge=0)
    model_provider: str | None = None
    model_reason: str | None = None
    model_attempts: list[dict[str, Any]] = Field(default_factory=list)
    review: dict[str, Any] | None = None
    candidate_signal_plan: SignalPlan | None = None
    candidate_legacy: Any = None
    final_signal_plan: SignalPlan | None = None
    final_legacy: Any = None
    safety_report: dict[str, Any] | None = None
    fallback_reason: list[str] = Field(default_factory=list)
    quality_issues: list[str] = Field(default_factory=list)
    errors: list[TraceError] = Field(default_factory=list)
    status: Literal["pending", "published", "batch_failed"] = "pending"
    publication_target: Literal["result_warehouse"] = "result_warehouse"
    latency_ms: float = Field(default=0, ge=0)
    stage_latency_ms: dict[str, float] = Field(default_factory=dict)
    _started_ns: int = PrivateAttr(default_factory=perf_counter_ns)
    _failed_stage: str | None = PrivateAttr(default=None)

    def capture_input(self, request, snapshot, *, has_datahub: bool) -> None:
        stamp = request.current_time
        valid_stamp = type(stamp) is int or type(stamp) is float and math.isfinite(stamp)
        self.input_timestamp = stamp if valid_stamp else None
        self.input_request = trace_value(request) if snapshot is None else None
        self.snapshot_status = "captured" if snapshot is not None else "unavailable" if has_datahub else "not_captured"
        self.traffic_snapshot = trace_value(snapshot) if snapshot is not None else None

    def capture_graph(self, decision, *, provider: str | None) -> None:
        self.route = list(decision.route)
        self.quality_issues = list(decision.quality_issues)
        for issue in decision.quality_issues:
            self.errors.append(TraceError(stage="graph", type="GraphQualityIssue", message=issue))
        for source, node, state in (("video", "primary_expert", decision.primary),
                                    ("radar", "fallback_expert", decision.fallback)):
            if node in decision.route and not any(item["source"] == source for item in self.expert_calls):
                self.expert_calls.append({
                    "source": source, "status": "ok" if state is not None else "failed",
                    "confidence": state.confidence if state is not None else None,
                    "missing_fields": list(state.missing_fields) if state is not None else [],
                })
        if decision.used_fallback:
            self.fallback_reason.append("expert:video_insufficient_or_unavailable")
        session = decision.cognition
        if session is None:
            return
        self.llm_participated = session.model_participated
        self.model_calls = session.model_calls
        self.model_provider = provider
        self.model_reason = session.reason
        self.model_attempts = trace_value(session.model_attempts)
        self.tool_calls = trace_value(session.tool_calls)
        self.review = trace_value(session.review.model_dump()) if session.review is not None else None
        for error in session.error_details:
            self.errors.append(TraceError.model_validate(error))
            self.fallback_reason.append(f"model:{error['stage']}")
        if session.reason not in {None, "planner_complete", "review_complete"}:
            self.fallback_reason.append(f"model:{session.reason}")

    def capture_plan(self, raw_plan, *, final: bool = False) -> None:
        try:
            plan = signal_plan_from_legacy(self.intersection_id, raw_plan).model_copy(deep=True)
        except ValueError:
            plan = None
        if final:
            self.final_signal_plan, self.final_legacy = plan, trace_value(raw_plan)
        else:
            self.candidate_signal_plan, self.candidate_legacy = plan, trace_value(raw_plan)

    def record_error(self, stage: str, error: Exception) -> None:
        self.errors.append(TraceError(stage=stage, type=type(error).__name__, message=str(error)[:1000]))

    @property
    def failed_stage(self) -> str:
        return self._failed_stage or "batch"

    def emit(self, logger, *, finished_ns: int | None = None) -> None:
        self.latency_ms = ((perf_counter_ns() if finished_ns is None else finished_ns) - self._started_ns) / 1_000_000
        try:
            # ASCII 转义避免供应商字符串的孤立 surrogate 破坏文件日志；拒绝非标准 NaN JSON。
            content = json.dumps(trace_value(self), ensure_ascii=True, allow_nan=False, separators=(",", ":"))
            logger.info("%s", content)
        except Exception as error:
            # 日志存储故障不得把已发布方案变成控制失败；向 stderr 明确报告，不静默吞掉。
            sys.stderr.write(f"Decision trace logging failed trace_id={self.trace_id} type={type(error).__name__}\n")


@contextmanager
def trace_stage(traces, stage: str):
    traces = tuple(traces)
    started = perf_counter_ns()
    try:
        yield
    except Exception:
        for trace in traces:
            trace._failed_stage = stage
        raise
    finally:
        elapsed = (perf_counter_ns() - started) / 1_000_000
        for trace in traces:
            trace.stage_latency_ms[stage] = elapsed
