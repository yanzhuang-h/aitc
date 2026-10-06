"""有界 Planner/Reviewer；模型动作只补充证据和意见，不计算配时。"""

from dataclasses import dataclass, field
from itertools import islice
import json
import math
from threading import Lock
from time import monotonic
from typing import Any

from pydantic import ValidationError

from app.config import ControlAgentSettings
from app.core.control.schemas import SignalPlan
from app.infrastructure.llm import ModelGateway, ModelMessage, ModelRequest
from app.infrastructure.llm.errors import ModelGatewayError, ModelUnavailableError
from infra.data.traffic_schemas import ExpertTrafficState, TrafficSnapshot

from .actions import (
    ACTION_ADAPTER, EmptyArguments, QueryRadarStateAction, QueryVideoStateAction,
    ReviewDecision, ToolAction, ToolObservation,
)
from .control_tools import ControlAgentTools, expert_summary, snapshot_summary
from .experts._state import ExpertContractError
from .prompts import PLANNER_PROMPT, REVIEWER_PROMPT


@dataclass
class CognitiveSession:
    """本轮路口独立持有；共享 controller 不能保存上一轮结果。"""

    model_calls: int = 0
    observations: list[ToolObservation] = field(default_factory=list)
    expert_states: dict[str, ExpertTrafficState] = field(default_factory=dict)
    review: ReviewDecision | None = None
    reason: str | None = None
    errors: list[str] = field(default_factory=list)
    model_participated: bool = False
    context_truncated: bool = False


_PLANNER_TOOLS = frozenset({
    "query_traffic_state", "query_history", "query_video_state", "query_radar_state",
    "run_control_policy", "report_anomaly",
})
_REVIEWER_TOOLS = _PLANNER_TOOLS | {"review_signal_plan"}
_EXPECTED_ERRORS = (
    ModelGatewayError, ValidationError, TimeoutError, ConnectionError,
    ExpertContractError, NotImplementedError,
)
_SERVICE_ERRORS = (ModelUnavailableError, TimeoutError, ConnectionError)


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    """显式省略过长/非 JSON 观测，保留完整 JSON 而不截取编码结果。"""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"omitted": "non_finite_number"}
    if isinstance(value, str):
        return value if len(value) <= 200 else value[:200] + "[omitted]"
    if depth >= 4:
        return {"omitted": "depth_limit"}
    if isinstance(value, dict):
        items = islice(value.items(), 8)
        result = {
            str(key)[:100]: _bounded_value(item, depth=depth + 1)
            for key, item in items if isinstance(key, (str, int, float))
        }
        omitted = len(value) - len(result)
        if omitted:
            result["_omitted_items"] = omitted
        return result
    if isinstance(value, (list, tuple)):
        result = [_bounded_value(item, depth=depth + 1) for item in value[:8]]
        if len(value) > 8:
            result.append({"omitted_items": len(value) - 8})
        return result
    return {"omitted_type": type(value).__name__}


def _has_omissions(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in {"omitted", "omitted_type", "omitted_items", "_omitted_items"}
                   or (item is True and (key == "truncated" or key.endswith("_truncated")))
                   or _has_omissions(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_has_omissions(item) for item in value)
    return isinstance(value, str) and value.endswith("[omitted]")


class CognitiveController:
    """共享网关和服务故障冷却；每路口独立会话、单轮严格调用预算。"""

    def __init__(
        self, gateway: ModelGateway, tools: ControlAgentTools,
        settings: ControlAgentSettings, logger=None,
    ) -> None:
        self.gateway = gateway
        self.tools = tools
        self.settings = ControlAgentSettings.model_validate(settings)
        self.logger = logger
        self._cooldown_lock = Lock()
        self._cooldown_until = 0.0

    def plan(
        self, session: CognitiveSession, *, intersection_id: str,
        snapshot: TrafficSnapshot | None, primary: ExpertTrafficState | None,
        fallback: ExpertTrafficState | None = None,
    ) -> None:
        # 即使总预算为 1，也给最终候选审查保留一次调用。
        self._run(
            session, phase="planner", intersection_id=intersection_id,
            snapshot=snapshot, primary=primary, fallback=fallback, candidate=None,
            call_limit=max(0, self.settings.max_model_calls - 1),
        )

    def review(
        self, session: CognitiveSession, *, intersection_id: str,
        snapshot: TrafficSnapshot | None, primary: ExpertTrafficState | None,
        fallback: ExpertTrafficState | None, candidate: SignalPlan | None,
    ) -> None:
        if session.review is not None:
            return
        if candidate is None:
            session.reason = "review_candidate_unavailable"
            return
        self._run(
            session, phase="reviewer", intersection_id=intersection_id,
            snapshot=snapshot, primary=primary, fallback=fallback, candidate=candidate,
            call_limit=self.settings.max_model_calls,
        )

    def _available(self, session: CognitiveSession) -> bool:
        if not self.settings.enabled:
            session.reason = "disabled"
            return False
        if not self.gateway.enabled:
            session.reason = "model_disabled"
            return False
        with self._cooldown_lock:
            cooling = monotonic() < self._cooldown_until
        if cooling:
            session.reason = "model_cooldown"
            return False
        return True

    def _run(
        self, session: CognitiveSession, *, phase: str, intersection_id: str,
        snapshot: TrafficSnapshot | None, primary: ExpertTrafficState | None,
        fallback: ExpertTrafficState | None, candidate: SignalPlan | None,
        call_limit: int,
    ) -> None:
        allowed = _PLANNER_TOOLS if phase == "planner" else _REVIEWER_TOOLS
        while session.model_calls < call_limit:
            if not self._available(session):
                return
            try:
                messages = self._messages(
                    session, phase=phase, intersection_id=intersection_id,
                    snapshot=snapshot, primary=primary, fallback=fallback, candidate=candidate,
                )
            except _EXPECTED_ERRORS as error:
                self._failure(session, error, "context_error", intersection_id)
                return
            if messages is None:
                return
            session.model_calls += 1
            session.model_participated = True
            try:
                response = self.gateway.invoke_sync(ModelRequest(
                    messages=messages, temperature=0, top_p=1, max_tokens=512,
                    max_retries=0, timeout_seconds=self.settings.timeout_seconds,
                ))
            except _EXPECTED_ERRORS as error:
                self._failure(session, error, "model_error", intersection_id)
                return
            try:
                action = ACTION_ADAPTER.validate_json(response.content)
            except ValidationError as error:
                self._failure(session, error, "invalid_action", intersection_id)
                return
            if action.tool not in allowed:
                self._failure(
                    session, ExpertContractError(f"{action.tool} is forbidden during {phase}"),
                    "invalid_action", intersection_id,
                )
                return
            try:
                observation = self._execute(
                    session, action, intersection_id=intersection_id, snapshot=snapshot,
                    primary=primary, fallback=fallback, candidate=candidate,
                )
                if action.tool == "run_control_policy" and phase == "planner":
                    session.reason = "planner_complete"
                    return
                if action.tool == "review_signal_plan":
                    if observation.status != "ok":
                        session.reason = "review_candidate_unavailable"
                        return
                    session.review = action.arguments
                    if self.logger is not None:
                        log = (self.logger.warning if session.review.decision in {
                            "WARN", "SUGGEST_ADJUSTMENT", "FALLBACK",
                        } else self.logger.info)
                        log("Cognitive review %s", json.dumps({
                            "intersection_id": intersection_id, "reported_by": "model",
                            "advisory_only": True,
                            **session.review.model_dump(exclude_none=True),
                        }, ensure_ascii=True))
                    if session.review.decision == "REQUEST_MORE_DATA":
                        query = (QueryVideoStateAction if session.review.source == "video"
                                 else QueryRadarStateAction)(
                            tool=f"query_{session.review.source}_state", arguments=EmptyArguments(),
                        )
                        # 明确补读一次，无再次模型调用，不重新运行 selector。
                        self._execute(
                            session, query, intersection_id=intersection_id, snapshot=snapshot,
                            primary=primary, fallback=fallback, candidate=candidate,
                        )
                    session.reason = "review_complete"
                    return
            except _EXPECTED_ERRORS as error:
                self._failure(session, error, "tool_error", intersection_id)
                return
        session.reason = ("planner_budget_exhausted" if phase == "planner"
                          else "review_budget_exhausted")

    def _execute(
        self, session: CognitiveSession, action: ToolAction, *, intersection_id: str,
        snapshot: TrafficSnapshot | None, primary: ExpertTrafficState | None,
        fallback: ExpertTrafficState | None, candidate: SignalPlan | None,
    ) -> ToolObservation:
        observation = ToolObservation.model_validate(self.tools.execute(
            action, intersection_id=intersection_id, snapshot=snapshot,
            primary=session.expert_states.get("video", primary),
            fallback=session.expert_states.get("radar", fallback), candidate=candidate,
        ))
        if observation.intersection_id != intersection_id or observation.tool != action.tool:
            raise ExpertContractError("tool observation does not match this action and intersection")
        if (action.tool == "query_traffic_state" and observation.expert_state is not None
                and observation.expert_state.source != action.arguments.source):
            raise ExpertContractError("tool expert does not match the requested traffic source")
        session.observations.append(observation)
        if observation.expert_state is not None:
            session.expert_states[observation.expert_state.source] = observation.expert_state
        if action.tool == "report_anomaly" and observation.status == "ok" and self.logger is not None:
            self.logger.warning("Cognitive anomaly %s", json.dumps({
                "intersection_id": intersection_id, "reported_by": "model",
                "advisory_only": True, "observation_verified": False,
                **action.arguments.model_dump(),
            }, ensure_ascii=True))
        return observation

    def _failure(
        self, session: CognitiveSession, error: Exception, reason: str, intersection_id: str,
    ) -> None:
        if isinstance(error, _SERVICE_ERRORS):
            with self._cooldown_lock:
                self._cooldown_until = max(
                    self._cooldown_until, monotonic() + self.settings.failure_cooldown_seconds,
                )
        detail = f"{type(error).__name__}: {error}"[:1000]
        session.reason = reason
        session.errors.append(detail)
        if self.logger is not None:
            self.logger.warning("Cognitive control %s: %s: %s", intersection_id, reason, detail)

    def _messages(
        self, session: CognitiveSession, *, phase: str, intersection_id: str,
        snapshot: TrafficSnapshot | None, primary: ExpertTrafficState | None,
        fallback: ExpertTrafficState | None, candidate: SignalPlan | None,
    ) -> list[ModelMessage] | None:
        prompt = PLANNER_PROMPT if phase == "planner" else REVIEWER_PROMPT
        primary = session.expert_states.get("video", primary)
        fallback = session.expert_states.get("radar", fallback)
        if snapshot is not None and snapshot.cross_id != intersection_id:
            raise ExpertContractError("context snapshot belongs to another intersection")
        if candidate is not None and candidate.intersection_id != intersection_id:
            raise ExpertContractError("context candidate belongs to another intersection")
        for expert, source in ((primary, "video"), (fallback, "radar")):
            if expert is not None and (expert.observation.cross_id != intersection_id
                                       or expert.source != source):
                raise ExpertContractError("context expert does not match the intersection and source")
        context = {
            "intersection_id": intersection_id, "phase": phase,
            "model_calls_remaining": self.settings.max_model_calls - session.model_calls,
            "summary_omissions_explicit": True,
            "snapshot": snapshot_summary(snapshot),
            "primary": expert_summary(primary),
            "fallback": expert_summary(fallback),
            "candidate": candidate.model_dump(mode="json") if candidate is not None else None,
            "tool_observations": [
                {"tool": item.tool, "status": item.status, "data": _bounded_value(item.data)}
                for item in session.observations
            ],
        }
        if _has_omissions(context):
            session.context_truncated = True
        context["context_truncated"] = session.context_truncated
        # 观测可能含不完整 Unicode；内层 JSON 转义保证实际 UTF-8 传输可编码。
        content = json.dumps(context, ensure_ascii=True, allow_nan=False)
        if len(prompt) + len(content) > self.settings.max_context_chars:
            session.context_truncated = True
            # 重建有效最小 JSON，保留路口、候选和质量；明确列出省略项。
            context = {
                "intersection_id": intersection_id, "phase": phase,
                "context_truncated": True,
                "omitted": ["snapshot_records", "expert_observations", "tool_observation_data"],
                "candidate": candidate.model_dump(mode="json") if candidate is not None else None,
                "primary_confidence": primary.confidence if primary is not None else None,
                "primary_missing_fields": _bounded_value(primary.missing_fields) if primary is not None else None,
                "fallback_confidence": fallback.confidence if fallback is not None else None,
                "tool_statuses": [{"tool": item.tool, "status": item.status} for item in session.observations],
            }
            content = json.dumps(context, ensure_ascii=True, allow_nan=False)
        if len(prompt) + len(content) > self.settings.max_context_chars:
            session.reason = "context_budget_exceeded"
            return None
        return [ModelMessage(role="system", content=prompt), ModelMessage(role="user", content=content)]
