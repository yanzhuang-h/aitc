import json
import time
import unittest

from pydantic import ValidationError

from agent.actions import ACTION_ADAPTER, ReviewDecision, ToolObservation
from agent.control_tools import ControlAgentTools
from agent.experts._state import ExpertContractError
from app.core.control.adapters import signal_plan_from_legacy
from infra.data.classifier import DataKind, DataSource
from infra.data.datahub import TrafficDataHub
from infra.data.traffic_schemas import ExpertTrafficState, RawTrafficEvent, TrafficSnapshot


def action(tool, **arguments):
    return ACTION_ADAPTER.validate_json(json.dumps({"tool": tool, "arguments": arguments}))


class FixedExpert:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def extract(self, intersection_id):
        self.calls.append(intersection_id)
        return self.state


class ControlActionContractTests(unittest.TestCase):
    def test_seven_actions_round_trip_with_strict_argument_objects(self):
        arguments = {
            "query_traffic_state": {}, "query_history": {},
            "query_video_state": {}, "query_radar_state": {},
            "run_control_policy": {},
            "review_signal_plan": {"decision": "ACCEPT", "reason": "已有方案可供确定性检查"},
            "report_anomaly": {"kind": "data_missing", "reason": "未观测到视频事件"},
        }
        for tool, args in arguments.items():
            with self.subTest(tool=tool):
                parsed = action(tool, **args)
                self.assertEqual(ACTION_ADAPTER.validate_json(parsed.model_dump_json()), parsed)
                self.assertFalse(type(parsed).model_json_schema()["additionalProperties"])

    def test_rejects_unknown_tools_extra_fields_and_algorithm_arguments(self):
        for value in (
            {"tool": "set_signal_plan", "arguments": {}},
            {"tool": "run_control_policy", "arguments": {"intersection_id": "other"}},
            {"tool": "run_control_policy", "arguments": {"traffic_vector": [1]}},
            {"tool": "run_control_policy", "arguments": {"phase_times": [30] * 8}},
            {"tool": "query_video_state", "arguments": [], "intersection_id": "other"},
            {"tool": "query_video_state"},
            {"tool": "query_traffic_state", "arguments": {"source": "tcp"}},
            {"tool": "report_anomaly", "arguments": {"kind": "incident", "reason": " "}},
            {"tool": "report_anomaly", "arguments": {"kind": "incident", "reason": "a" * 1001}},
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ACTION_ADAPTER.validate_json(json.dumps(value))

    def test_history_limit_rejects_coercion_and_out_of_bounds(self):
        self.assertEqual(action("query_history").arguments.limit, 3)
        for value in (True, "3", 3.0, 0, 21, None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                action("query_history", limit=value)

    def test_review_decisions_have_only_their_corresponding_optional_fields(self):
        for decision in ("ACCEPT", "WARN", "FALLBACK"):
            self.assertEqual(ReviewDecision(decision=decision, reason="检查记录").decision, decision)
        self.assertEqual(ReviewDecision(decision="REQUEST_MORE_DATA", reason="补读", source="radar").source, "radar")
        self.assertEqual(ReviewDecision(decision="SUGGEST_ADJUSTMENT", reason="建议", suggestion="由确定性策略复核").suggestion,
                         "由确定性策略复核")
        for patch in (
            {"decision": "REQUEST_MORE_DATA"},
            {"decision": "REQUEST_MORE_DATA", "source": "internet"},
            {"decision": "SUGGEST_ADJUSTMENT"},
            {"decision": "ACCEPT", "source": "video"},
            {"decision": "WARN", "suggestion": "改时长"},
            {"decision": "FALLBACK", "phase_times": [30] * 8},
            {"decision": "ACCEPT", "plan": [30] * 10},
            {"decision": "ACCEPT", "safe": True},
        ):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                ReviewDecision.model_validate({"reason": "检查记录", **patch})

    def test_observation_revalidates_expert_identity(self):
        state = ExpertTrafficState(source="radar", observation=TrafficSnapshot(cross_id="other", current_time=1),
                                   confidence=1)
        with self.assertRaises(ValidationError):
            ToolObservation(tool="query_radar_state", intersection_id="road", status="ok", data={}, expert_state=state)


class ControlAgentToolsTests(unittest.TestCase):
    def setUp(self):
        self.hub = TrafficDataHub(memory_window=3)
        self.snapshot = TrafficSnapshot(
            cross_id="road", current_time=10, traffic_vector=[1, 2, 3, 4],
            flow_map={10: {"count": {"L": 1}}}, queue_map={10: {"L": [2]}},
        )
        self.video = FixedExpert(ExpertTrafficState(source="video", observation=self.snapshot,
                                                   confidence=1))
        self.radar = FixedExpert(ExpertTrafficState(
            source="radar", observation=TrafficSnapshot(cross_id="road", current_time=10),
            confidence=0, missing_fields=["radar_map", "boyan_map"],
        ))
        self.tools = ControlAgentTools(self.hub, self.video, self.radar)

    def execute(self, tool, arguments=None, **context):
        return self.tools.execute(action(tool, **(arguments or {})), intersection_id="road", **context)

    def test_failed_current_snapshot_never_uses_previous_latest(self):
        self.hub.capture(self.snapshot)
        result = self.execute("query_traffic_state")
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.data["snapshot"])
        self.assertFalse(result.data["snapshot_current_round"])
        self.assertIn("snapshot_current_round", result.data["missing_fields"])
        self.assertIsNotNone(self.hub.latest("road"))

    def test_source_without_events_is_unavailable_even_with_full_current_snapshot(self):
        result = self.execute("query_traffic_state", {"source": "radar"}, snapshot=self.snapshot)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.data["event_count"], 0)
        self.assertIn("radar_observation", result.data["missing_fields"])
        self.assertEqual(result.data["expert"]["confidence"], 0)

    def test_current_event_counts_and_quality_are_real_and_road_isolated(self):
        received = time.time() - 1
        for road in ("road", "other"):
            self.hub.ingest(RawTrafficEvent(
                kind=DataKind.FLOW, source=DataSource.TCP, received_at=received,
                intersection_id=road,
                payload={"ycsb_xsfx": "L", "jtll_ddbh": "1", "ycsb_cdbh": "0",
                         "ts": str(int(received * 1000))},
            ))
        result = self.execute("query_traffic_state", {"source": "video"}, snapshot=self.snapshot)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.data["event_count"], 1)
        self.assertEqual(result.data["event_counts_by_kind"], {"flow": 1})
        self.assertIn("queue", result.data["missing_fields"])
        self.assertEqual(result.data["quality_issues"], [])
        self.assertTrue(result.data["snapshot_current_round"])

    def test_history_is_bounded_and_separates_saved_rounds_from_current_context(self):
        for timestamp in (1, 2, 3, 4):
            self.hub.capture(TrafficSnapshot(cross_id="road", current_time=timestamp))
        self.hub.capture(TrafficSnapshot(cross_id="other", current_time=100))
        current = TrafficSnapshot(cross_id="road", current_time=4)
        result = self.execute("query_history", {"limit": 2}, snapshot=current)
        rows = result.data["snapshots"]
        self.assertEqual([row["current_time"] for row in rows], [3, 4])
        self.assertEqual([row["is_current_snapshot"] for row in rows], [False, True])
        self.assertEqual(result.data["current_round_time"], 4)
        self.assertEqual(result.data["origin"], "captured_history")
        rows[-1]["current_time"] = 99
        self.assertEqual(self.hub.latest("road").current_time, 4)

    def test_summaries_bound_large_vectors_maps_and_strings(self):
        snapshot = TrafficSnapshot(
            cross_id="road", current_time=10, traffic_vector=list(range(10000)),
            flow_map={i: {"vendor": "s" * 10000} for i in range(100)},
        )
        result = self.execute("query_traffic_state", snapshot=snapshot)
        summary = result.data["snapshot"]
        self.assertEqual(summary["traffic_vector"]["sample"], list(range(8)))
        self.assertEqual(summary["traffic_vector"]["entries"], 10000)
        self.assertTrue(summary["traffic_vector"]["truncated"])
        self.assertEqual(summary["flow_map"]["entries"], 100)
        self.assertLess(len(json.dumps(result.data)), 4000)

    def test_nonfinite_opaque_values_are_explicit_omissions_in_json_summary(self):
        snapshot = TrafficSnapshot(cross_id="road", current_time=10,
                                   traffic_vector=[float("nan"), float("inf"), 1])
        result = self.execute("query_traffic_state", snapshot=snapshot)
        values = result.data["snapshot"]["traffic_vector"]["sample"]
        self.assertEqual(values[:2], [{"omitted": "non_finite_number"}] * 2)
        self.assertEqual(values[2], 1)
        json.dumps(result.data, allow_nan=False)

    def test_global_algorithm_maps_are_scoped_in_current_and_history_summaries(self):
        snapshot = TrafficSnapshot(
            cross_id="road", current_time=10,
            predicted_flow={"other": "sensitive-flow", "road": {"avg_dur1": [1, 2]}},
            predicted_queue={"other": "sensitive-queue", "road": {"L": [3, 4]}},
            previous_coordinate={"other": "sensitive-coordinate", "road": {"offset": 5}},
        )
        self.hub.capture(snapshot)
        for result in (self.execute("query_traffic_state", snapshot=snapshot),
                       self.execute("query_history", snapshot=snapshot)):
            content = json.dumps(result.data)
            self.assertNotIn("sensitive", content)
            self.assertNotIn("other", content)
            self.assertIn("predicted_flow", content)
        self.assertEqual(snapshot.predicted_flow["other"], "sensitive-flow")
        self.assertEqual(self.hub.latest("road").previous_coordinate["other"], "sensitive-coordinate")

    def test_outside_intersection_maps_are_omitted_without_claiming_global_absence(self):
        snapshot = TrafficSnapshot(
            cross_id="road", current_time=10,
            predicted_flow={"other": "sensitive-flow"},
            predicted_queue={"other": "sensitive-queue"},
            previous_coordinate={"other": "sensitive-coordinate"},
        )
        result = self.execute("query_traffic_state", snapshot=snapshot)
        summary = result.data["snapshot"]
        self.assertEqual(summary["omitted_not_scoped"],
                         ["predicted_flow", "predicted_queue", "previous_coordinate"])
        self.assertFalse(set(summary["available_fields"]) & set(summary["scoped_fields"]))
        self.assertNotIn("sensitive", json.dumps(summary))

    def test_expert_queries_reuse_and_copy_host_states(self):
        supplied = self.video.state
        result = self.execute("query_video_state", primary=supplied)
        self.assertEqual(self.video.calls, [])
        self.assertEqual(result.status, "ok")
        result.expert_state.observation.flow_map[10]["count"]["L"] = 99
        self.assertEqual(supplied.observation.flow_map[10]["count"]["L"], 1)
        self.execute("query_traffic_state", {"source": "video"}, primary=supplied)
        self.assertEqual(self.video.calls, [])

    def test_expert_queries_extract_only_when_needed_and_keep_missing_fields(self):
        result = self.execute("query_radar_state")
        self.assertEqual(self.radar.calls, ["road"])
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.data["missing_fields"], ["radar_map", "boyan_map"])

    def test_expert_source_and_intersection_mismatch_are_contract_errors(self):
        for state in (
            ExpertTrafficState(source="radar", observation=self.snapshot, confidence=1),
            ExpertTrafficState(source="video", observation=TrafficSnapshot(cross_id="other", current_time=1), confidence=1),
        ):
            self.video.state = state
            with self.subTest(state=state), self.assertRaises(ExpertContractError):
                self.execute("query_video_state")

    def test_host_context_identity_cannot_be_changed_by_a_model_action(self):
        with self.assertRaises(ExpertContractError):
            self.execute("query_history", snapshot=TrafficSnapshot(cross_id="other", current_time=1))
        with self.assertRaises(ExpertContractError):
            self.execute("query_video_state", primary=self.radar.state)
        with self.assertRaises(ValidationError):
            self.tools.execute(action("query_history"), intersection_id=123)

    def test_mutated_action_and_nested_snapshot_are_revalidated(self):
        parsed = action("query_history")
        object.__setattr__(parsed.arguments, "limit", True)
        with self.assertRaises(ValidationError):
            self.tools.execute(parsed, intersection_id="road")
        invalid = self.snapshot
        object.__setattr__(invalid, "current_time", "10")
        with self.assertRaises(ValidationError):
            self.execute("query_traffic_state", snapshot=invalid)

    def test_control_policy_tool_does_not_run_an_algorithm(self):
        missing = self.execute("run_control_policy")
        self.assertEqual(missing.status, "unavailable")
        self.assertEqual(missing.data["next_step"], "run_control_policy")
        candidate = signal_plan_from_legacy("road", [30, 20] + [0] * 8)
        result = self.execute("run_control_policy", candidate=candidate)
        self.assertEqual(result.data["candidate"], candidate.model_dump(mode="json"))
        self.assertTrue(result.data["algorithm_already_ran"])
        self.assertEqual(self.video.calls + self.radar.calls, [])

    def test_review_is_advisory_and_cannot_modify_candidate(self):
        args = {"decision": "SUGGEST_ADJUSTMENT", "reason": "排队较长", "suggestion": "由后续确定性检查复核"}
        self.assertEqual(self.execute("review_signal_plan", args).status, "unavailable")
        candidate = signal_plan_from_legacy("road", [30, 20] + [0] * 8)
        before = candidate.model_copy(deep=True)
        result = self.execute("review_signal_plan", args, candidate=candidate)
        self.assertEqual(result.data["review"], args)
        self.assertTrue(result.data["advisory_only"])
        self.assertNotIn("safe", result.data)
        self.assertEqual(candidate, before)

    def test_model_anomaly_is_reported_without_creating_a_sensor_event(self):
        result = self.execute("report_anomaly", {"kind": "incident", "reason": "模型推测"})
        self.assertEqual(result.data["reported_by"], "model")
        self.assertFalse(result.data["observation_verified"])
        self.assertEqual(self.hub.query("road").events, [])
        self.assertIsNone(self.hub.latest("road"))

    def test_programming_errors_propagate(self):
        def broken(_intersection_id):
            raise RuntimeError("broken extractor")
        self.video.extract = broken
        with self.assertRaisesRegex(RuntimeError, "broken extractor"):
            self.execute("query_video_state")


if __name__ == "__main__":
    unittest.main()
