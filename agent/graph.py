"""最小 LangGraph 控制流程；节点仅编排专家、原控制策略和契约校验。"""

from typing import Callable, Literal

from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, RetryPolicy
from pydantic import TypeAdapter, ValidationError

from app.core.control.adapters import signal_plan_from_legacy
from app.core.control.policies import BaselineController
from app.core.control.policies.baseline import LegacySelection
from app.core.control.schemas import SignalPlan
from infra.data.datahub import TrafficDataHub
from infra.data.traffic_adapters import snapshot_to_legacy
from infra.data.traffic_schemas import ExpertTrafficState, TrafficSnapshot
from lib.control_functions.types import IntersectionControlRequest

from ._langgraph_compat import isolate_checkpoint_randomness
from .cognitive import CognitiveController, CognitiveSession
from .experts._state import ExpertContractError
from .state import ControlContext, ControlDecision, ControlState


_SNAPSHOT_ADAPTER = TypeAdapter(TrafficSnapshot)
_EXPERT_ADAPTER = TypeAdapter(ExpertTrafficState)
_READ_RETRY = RetryPolicy(
    max_attempts=2, initial_interval=0.01, backoff_factor=1, jitter=False,
    retry_on=(TimeoutError, ConnectionError),
)


class ControlGraph:
    """共享编译图，使用每次调用的 Runtime context 隔离原请求与 selector。"""

    def __init__(
        self, datahub: TrafficDataHub, *, primary_expert, fallback_expert,
        control_policy: BaselineController, logger=None,
        cognitive_controller: CognitiveController | None = None,
    ) -> None:
        isolate_checkpoint_randomness()
        self.datahub = datahub
        self.primary_expert = primary_expert
        self.fallback_expert = fallback_expert
        self.control_policy = control_policy
        self.logger = logger
        self.cognitive_controller = cognitive_controller
        builder = StateGraph(ControlState, context_schema=ControlContext)
        builder.add_node("load_context", self._load_context)
        builder.add_node(
            "primary_expert", self._primary_expert, retry_policy=_READ_RETRY,
            error_handler=self._expert_error,
        )
        builder.add_node(
            "fallback_expert", self._fallback_expert, retry_policy=_READ_RETRY,
            error_handler=self._expert_error,
        )
        builder.add_node("control_policy", self._control_policy)
        builder.add_node("validate", self._validate)
        builder.add_edge(START, "load_context")
        builder.add_edge("load_context", "primary_expert")
        routes = {"control_policy": "control_policy", "fallback_expert": "fallback_expert"}
        if cognitive_controller is not None:
            routes["planner"] = "planner"
        builder.add_conditional_edges("primary_expert", self._next_after_primary, routes)
        builder.add_edge("fallback_expert", "control_policy")
        builder.add_edge("control_policy", "validate")
        if cognitive_controller is None:
            builder.add_edge("validate", END)
        else:
            builder.add_node("planner", self._planner)
            builder.add_node("review", self._review)
            builder.add_edge("planner", "fallback_expert")
            builder.add_conditional_edges("validate", self._next_after_validate)
            builder.add_edge("review", END)
        self.graph = builder.compile()

    def execute_legacy(
        self, request: IntersectionControlRequest, *,
        selector: Callable[[IntersectionControlRequest], LegacySelection] | None = None,
        snapshot: TrafficSnapshot | None = None,
    ) -> ControlDecision:
        """兼容生产的原四元组；契约问题不能提前阻断后续协调。"""
        return self._execute(ControlContext(
            request=request,
            selector=selector if selector is not None else self.control_policy.select_legacy,
            snapshot=snapshot,
        ))

    def select_legacy(self, request: IntersectionControlRequest) -> LegacySelection:
        return self.execute_legacy(request).selection

    def predict(self, state: TrafficSnapshot) -> SignalPlan:
        """严格新入口，返回单点候选；不代替最终业务安全校验。"""
        snapshot = _SNAPSHOT_ADAPTER.validate_python(state)
        decision = self._execute(ControlContext(
            request=snapshot_to_legacy(snapshot),
            selector=self.control_policy.select_legacy, strict=True, snapshot=snapshot,
        ))
        assert decision.candidate is not None
        return decision.candidate

    def _execute(self, context: ControlContext) -> ControlDecision:
        state = self.graph.invoke(
            {"intersection_id": context.request.cross_id}, context=context,
        )
        return ControlDecision(
            selection=state["selection"], candidate=state["candidate"],
            primary=state["primary"], fallback=state["fallback"],
            used_fallback=state["used_fallback"], quality_issues=state["quality_issues"],
            route=state["route"],
            cognition=state["cognition"],
        )

    @staticmethod
    def _load_context(state: ControlState, runtime: Runtime[ControlContext]) -> dict:
        # 来源投影缺少预测和上一轮协调，必须保留原完整算法请求。
        return {
            "request": runtime.context.request, "snapshot": runtime.context.snapshot,
            "primary": None, "fallback": None, "used_fallback": False,
            "candidate": None, "quality_issues": (), "route": ("load_context",),
            "cognition": None,
        }

    def _primary_expert(self, state: ControlState) -> dict:
        primary = self._read_expert(self.primary_expert, state["intersection_id"], "video")
        return {"primary": primary, "route": (*state["route"], "primary_expert")}

    @staticmethod
    def _enough_data(state: ControlState) -> Literal["control_policy", "fallback_expert"]:
        primary = state["primary"]
        if (primary is not None and primary.confidence == 1
                and primary.observation.flow_map and primary.observation.queue_map
                and not {"flow_map", "queue_map"}.intersection(primary.missing_fields)):
            return "control_policy"
        return "fallback_expert"

    def _next_after_primary(self, state: ControlState) -> Literal["control_policy", "fallback_expert", "planner"]:
        route = self._enough_data(state)
        return "planner" if route == "fallback_expert" and self.cognitive_controller is not None else route

    def _planner(self, state: ControlState) -> dict:
        session = CognitiveSession()
        self.cognitive_controller.plan(
            session, intersection_id=state["intersection_id"],
            snapshot=state["snapshot"], primary=state["primary"],
        )
        return {"cognition": session, "route": (*state["route"], "planner")}

    @staticmethod
    def _next_after_validate(state: ControlState) -> Literal["review", "__end__"]:
        return "review" if state["cognition"] is not None and state["candidate"] is not None else END

    def _review(self, state: ControlState) -> dict:
        session = state["cognition"]
        self.cognitive_controller.review(
            session, intersection_id=state["intersection_id"], snapshot=state["snapshot"],
            primary=state["primary"], fallback=state["fallback"], candidate=state["candidate"],
        )
        return {"cognition": session, "route": (*state["route"], "review")}

    def _fallback_expert(self, state: ControlState) -> dict:
        session = state["cognition"]
        cached = session.expert_states.get("radar") if session is not None else None
        fallback = (
            self._check_expert(cached, state["intersection_id"], "radar") if cached is not None
            else self._read_expert(self.fallback_expert, state["intersection_id"], "radar")
        )
        return {
            "fallback": fallback, "used_fallback": True,
            "route": (*state["route"], "fallback_expert"),
        }

    @staticmethod
    def _read_expert(expert, intersection_id: str, source: str) -> ExpertTrafficState:
        return ControlGraph._check_expert(expert.extract(intersection_id), intersection_id, source)

    @staticmethod
    def _check_expert(result, intersection_id: str, source: str) -> ExpertTrafficState:
        result = _EXPERT_ADAPTER.validate_python(result)
        if result.source != source or result.observation.intersection_id != intersection_id:
            raise ExpertContractError(f"{source} expert returned a different source or intersection")
        return result

    def _expert_error(self, state: ControlState, error: NodeError) -> Command:
        # 已知读取/契约故障显式降级；编程错误继续传播，避免掩盖缺陷。
        failure = error.error
        if not isinstance(failure, (TimeoutError, ConnectionError, ValidationError, ExpertContractError)):
            raise failure
        issue = f"{error.node}: {type(failure).__name__}: {failure}"
        if self.logger is not None:
            self.logger.warning(
                "Control graph %s expert failed: %s", state["intersection_id"], issue,
                exc_info=(type(failure), failure, failure.__traceback__),
            )
        update = {
            "quality_issues": (*state["quality_issues"], issue),
            "route": (*state["route"], error.node),
        }
        if error.node == "primary_expert":
            return Command(update=update, goto="planner" if self.cognitive_controller is not None else "fallback_expert")
        update["used_fallback"] = True
        return Command(update=update, goto="control_policy")

    @staticmethod
    def _control_policy(state: ControlState, runtime: Runtime[ControlContext]) -> dict:
        # selector 可能有经验记录和随机诊断等副作用，因此此节点不重试。
        return {
            "selection": runtime.context.selector(state["request"]),
            "route": (*state["route"], "control_policy"),
        }

    def _validate(self, state: ControlState, runtime: Runtime[ControlContext]) -> dict:
        plan, _, _, _ = state["selection"]
        candidate = None
        issues = state["quality_issues"]
        try:
            candidate = signal_plan_from_legacy(state["intersection_id"], plan)
        except ValueError as error:
            if runtime.context.strict:
                raise
            issue = f"candidate_contract: {error}"
            issues = (*issues, issue)
            if self.logger is not None:
                self.logger.warning("Control graph %s: %s", state["intersection_id"], issue)
        # 原 phase_check 必须在批次全局协调后运行，不能在这里提前钳位。
        return {"candidate": candidate, "quality_issues": issues,
                "route": (*state["route"], "validate")}
