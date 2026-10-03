"""Deterministic legacy replay inputs; no control formulas are reimplemented here.

Regenerate the golden file only after reviewing an intended behavior change:
    .venv/bin/python -m test.fixtures.v2_baseline_controller
"""

import copy
import hashlib
import io
import json
import os
import random
import re
import time
from contextlib import ExitStack, contextmanager, redirect_stdout
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

import Lambdas
import lib.Global_intersection_coordinate as global_control
import lib.floating_value as floating_value
import lib.lvbotest as green_wave
import lib.road_state as road_state
import phase_check as phase_checker
from infra.data import ResultSender, ResultWarehouse
from lib.control_functions.dqn_control import call_dqn_select
from lib.control_functions.types import IntersectionControlRequest
from lib.data_ANS import flow_allocator_shadow as shadow
from runtime.result_formatter import format_result


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_suffix(".json")
FIXED_TIME = 1790728200  # 2026-09-30 08:30:00 Asia/Shanghai, a workday.
SEED = 37
CHECKPOINT_IDS = (
    "1300360", "1300068", "1300086", "1300103", "2719089", "1300782",
    "2705050", "1300370", "1300373", "1300248",
)
SELECTOR_CASES = (
    ("timetable_rule", "1300103", "legacy"),
    ("old_experience", "1300068", "legacy"),
    ("pilot_new", "1300068", "new"),
    ("pilot_fallback", "1300068", "new"),
)


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 9, 30)

    @classmethod
    def fromtimestamp(cls, timestamp):
        return FixedDatetime.fromtimestamp(timestamp).date()


class FixedDatetime(datetime):
    """Keep legacy naive local datetime behavior independent of the host TZ."""

    @classmethod
    def fromtimestamp(cls, timestamp, tz=None):
        value = super().fromtimestamp(timestamp, tz or ZoneInfo("Asia/Shanghai"))
        return value if tz else value.replace(tzinfo=None)

    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(time.time(), tz)


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def config_sources():
    paths = (
        "lib/wwx.json", "lib/experience_pool/new_wwx.json", "lib/cross_info.json",
        "lib/road_info.json", "lib/road_state.json", "lib/floating_value.json",
        "lib/green_wave_corridors.json", "intersection_result_config.json",
        "time_schedule/schedule_json/FIne_turn.json",
    )
    sources = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
               for path in paths}
    schedules = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                 for cross_id in Lambdas.intersection_list
                 if (path := ROOT / f"time_schedule/schedule_json/Time_schedule_{cross_id}.json").exists()}
    sources["workday_schedules"] = {"count": len(schedules), "sha256": digest(schedules)}
    sources["intersection_order_and_groups"] = digest({
        "order": Lambdas.intersection_list,
        "internet": sorted(global_control.intern_road_id),
        "mixed": sorted(global_control.video_road),
        "flow": sorted(global_control.video_flow_road),
    })
    return sources


@contextmanager
def isolated_runtime(now=FIXED_TIME, *, mode="legacy", fallback=False):
    """Restore all mutable state touched by the real legacy replay on exit."""
    # Green-wave activation changes both configuration and state globals.
    # Capture data attributes only, excluding functions, classes and imports.
    green_values = {name: value
                    for name, value in vars(green_wave).items()
                    if not name.startswith("__")
                    and isinstance(value, (dict, list, set, str, bool, int, float, type(None)))}
    global_names = ("inter_road_state", "start", "cycle_green", "offset_green",
                    "cycle_done", "offset_done", "cnt", "fix_plan", "direction")
    global_values = {name: getattr(global_control, name)
                     for name in global_names}
    caches = [(module, module._cache_data, module._cache_mtime)
              for module in (road_state, floating_value)]
    shadow_cache = copy.deepcopy(shadow._JSON_CACHE)
    random_state = random.getstate()
    try:
        global_control.inter_road_state = {}
        green_wave.reset_green_wave_state()
        green_wave._GREEN_WAVE_CONFIG_MAP = {}
        for module, _, _ in caches:
            module._cache_mtime = None
        shadow._JSON_CACHE.clear()
        with TemporaryDirectory(prefix="aitc-baseline-") as directory, ExitStack() as stack:
            environment = {
                "AITC_FLOW_ALLOCATOR_PILOT_MODE": mode,
                "AITC_FLOW_ALLOCATOR_PILOT_ROADS": "1300068",
                "AITC_FLOW_ALLOCATOR_SHADOW_ROADS": "1300068",
                "AITC_FLOW_ALLOCATOR_SHADOW_ENABLED": "1",
                "AITC_FLOW_ALLOCATOR_SHADOW_TABLE": str(ROOT / "lib/experience_pool/new_wwx.json"),
                "AITC_FLOW_ALLOCATOR_SHADOW_CROSS_INFO": str(ROOT / "lib/cross_info.json"),
                "AITC_FLOW_ALLOCATOR_SHADOW_LOG_DIR": directory,
            }
            if fallback:
                # A missing external experience file exercises the production
                # evaluation-error fallback without altering control functions.
                environment["AITC_FLOW_ALLOCATOR_SHADOW_TABLE"] = str(Path(directory) / "missing.json")
            stack.enter_context(patch.dict(os.environ, environment))
            stack.enter_context(patch("time.time", return_value=now))
            stack.enter_context(patch("time.localtime", side_effect=lambda timestamp=None:
                                      FixedDatetime.fromtimestamp(time.time() if timestamp is None else timestamp).timetuple()))
            stack.enter_context(patch("lib.AITC_tool.date", FixedDate))
            stack.enter_context(patch("lib.DQN_Select.date", FixedDate))
            stack.enter_context(patch("lib.floating_value.date", FixedDate))
            for target in ("lib.Global_intersection_coordinate.datetime", "lib.lvbotest.datetime",
                           "lib.green_wave_functions.datetime", "lib.data_ANS.flow_allocator_shadow.datetime"):
                stack.enter_context(patch(target, FixedDatetime))
            stack.enter_context(patch("phase_check.intersection_result_config",
                                      json.loads((ROOT / "intersection_result_config.json").read_text())))
            stack.enter_context(patch("lib.green_wave_functions.GREEN_WAVE_CONFIG_PATH",
                                      ROOT / "lib/green_wave_corridors.json"))
            stack.enter_context(redirect_stdout(io.StringIO()))
            random.seed(SEED)
            yield Path(directory)
    finally:
        for name, value in global_values.items():
            setattr(global_control, name, value)
        for name, value in green_values.items():
            setattr(green_wave, name, value)
        for module, data, mtime in caches:
            module._cache_data, module._cache_mtime = data, mtime
        shadow._JSON_CACHE.clear()
        shadow._JSON_CACHE.update(shadow_cache)
        random.setstate(random_state)


def sensor_request(cross_id, now=FIXED_TIME, *, observed=False):
    """Explicit test observations in the runtime's existing sensor shapes."""
    request = IntersectionControlRequest(
        cross_id=cross_id, current_time=now,
        traffic_vector=[12, 9, 6, 3] if observed else [0] * 4,
        traffic_vector_duration2=[4, 3, 2, 1] if observed else [0] * 4,
        queue_vector={direction: [0] * 7 for direction in "LRUD"},
    )
    if observed:
        request.flow_map = {
            now - 600 + offset: {"pass": {
                direction: [0, 3 + index, 4, 2, 0, 0, 0]
                for index, direction in enumerate("UDLR")}}
            for offset in range(0, 600, 60)
        }
        request.extend_map = {
            now - 600 + offset: [{"CrossId": cross_id,
                                  "curStageNo": str(1 + (offset // 100) % 3),
                                  "time": (now - 600 + offset) * 1000}]
            for offset in range(600)
        }
        if cross_id == "1300103":
            request.stage_map = {
                now - 120: {"curStageNo": "1", "curStageLen": 0},
                now - 60: {"curStageNo": "2", "curStageLen": 0},
                now: {"curStageNo": "1", "curStageLen": 0},
            }
    return request


def shadow_summary(directory):
    records = [json.loads(line) for path in sorted(directory.glob("*.jsonl"))
               for line in path.read_text().splitlines()]
    fields = ("status", "runtime_mode", "selected_schedule_source", "selection_fallback_reason",
              "quality_passed", "normalization_mode", "new_schedule", "selected_schedule")
    return [{key: record[key] for key in fields if key in record} for record in records]


def selector_replay(selector=call_dqn_select):
    results = {}
    for name, cross_id, mode in SELECTOR_CASES:
        with isolated_runtime(mode=mode, fallback=name == "pilot_fallback") as directory:
            # Suppress only the expected missing-file logger traceback.
            with patch.object(shadow.LOGGER, "exception"):
                result = selector(sensor_request(cross_id, observed=True))
            results[name] = {"cross_id": cross_id, "legacy_result": list(result),
                             "shadow": shadow_summary(directory)}
    return results


def online_observations(now):
    # Real configured road IDs, with explicit synthetic speed observations.
    return {
        rid: {now - 60: [{"rid": rid, "time": now - 60, "jam_state_no": 0,
                          "speed": 18 + index % 10, "max_speed": 50, "nostop_speed": 45}],
              now: [{"rid": rid, "time": now, "jam_state_no": 0,
                     "speed": 20 + index % 10, "max_speed": 50, "nostop_speed": 45}]}
        for index, (rid, mapping) in enumerate(global_control.online_map_info.items())
        if isinstance(mapping, dict)
    }


class RecordingSocket:
    def __init__(self):
        self.frames = []

    def sendall(self, frame):
        self.frames.append(frame)


def full_replay(selector=call_dqn_select, coordinator=global_control.coordinate):
    """Run 186 selectors and all legacy processors twice with retained state."""
    rounds = []
    with isolated_runtime():
        previous_coordinate = {}
        for round_index in range(2):
            now = FIXED_TIME + 120 * round_index
            with patch("time.time", return_value=now):
                requests = {cross_id: sensor_request(cross_id, now, observed=cross_id in {"1300068", "1300103"})
                            for cross_id in Lambdas.intersection_list}
                for request in requests.values():
                    request.previous_coordinate = copy.deepcopy(previous_coordinate)
                selections = {cross_id: selector(request) for cross_id, request in requests.items()}
                action = {cross_id: result[0] for cross_id, result in selections.items()}
                coordinate_map = {cross_id: result[1] for cross_id, result in selections.items()}
                previous_coordinate = copy.deepcopy(coordinate_map)
                before = copy.deepcopy(action)
                coordinated = coordinator(action, coordinate_map, online_observations(now), {})
                after_coordinate = copy.deepcopy(coordinated)
                checked, report = phase_checker.phase_check(coordinated)
                payloads = [format_result(cross_id, checked[cross_id], requests[cross_id].traffic_vector,
                                          selections[cross_id][2], lambdas_module=Lambdas)
                            for cross_id in Lambdas.intersection_list]
                warehouse = ResultWarehouse()
                warehouse.replace(payloads)
                socket = RecordingSocket()
                disconnected = ResultSender().send_batch([socket], warehouse.snapshot())
                if disconnected:
                    raise AssertionError("recording TCP socket unexpectedly disconnected")
                rounds.append({
                    "timestamp": now, "before_coordinate": before,
                    "after_coordinate": after_coordinate, "after_phase_check": copy.deepcopy(checked),
                    "phase_report": report, "payloads": payloads, "tcp_frames": socket.frames,
                    "green_wave_state": copy.deepcopy(green_wave._GREEN_WAVE_STATE_MAP),
                    "internet_state": copy.deepcopy(global_control.inter_road_state),
                })
    return rounds


def compact_round(round_result):
    stages = ("before_coordinate", "after_coordinate", "after_phase_check", "phase_report")
    payload_by_id = {payload["additional"]["tlLogic"]["id"]: payload
                     for payload in round_result["payloads"]}
    return {
        "timestamp": round_result["timestamp"],
        "intersection_count": len(round_result["after_phase_check"]),
        "sha256": {**{stage: digest(round_result[stage]) for stage in stages},
                   "payloads": digest(round_result["payloads"]),
                   "tcp_bytes": hashlib.sha256(b"".join(round_result["tcp_frames"])).hexdigest(),
                   "green_wave_state": digest(round_result["green_wave_state"]),
                   "internet_state": digest(round_result["internet_state"])},
        "checkpoints": {
            cross_id: {**{stage: round_result[stage][cross_id] for stage in stages},
                       "payload": payload_by_id[cross_id]}
            for cross_id in CHECKPOINT_IDS
        },
        "green_wave_state": round_result["green_wave_state"],
    }


def build_fixture():
    return {
        "schema_version": 1,
        "provenance": {
            "baseline_commit": "f59bb50",
            "generated_with": "direct original call_dqn_select and coordinate; no BaselineController calls",
            "local_clock": "2026-09-30 08:30:00 and 08:32:00 Asia/Shanghai",
            "workday": True, "random_seed": SEED,
            "selector_order": "Lambdas.intersection_list, serial for reproducible random diagnostics",
            "test_input": "explicit synthetic runtime-shaped flow/extend/stage/online observations; real repository configurations",
            "pilot_fallback": "new mode with missing external experience file",
            "state": "empty Internet and green-wave state initially; retained across two rounds; restored after replay",
            "coordinate_arguments": "action, coordinate_map, online_map, overflow_map (four production arguments)",
            "scope": "fixed workday morning; not field-performance validation or every event/time branch",
        },
        "config_sources": config_sources(),
        "selectors": selector_replay(),
        "rounds": [compact_round(result) for result in full_replay()],
    }


if __name__ == "__main__":
    encoded = json.dumps(build_fixture(), ensure_ascii=False, indent=2)
    # Keep the legacy plan and diagnostic vectors readable on one line.
    encoded = re.sub(r"\[\n\s*-?\d+(?:\.\d+)?(?:,\n\s*-?\d+(?:\.\d+)?)*\n\s*\]",
                     lambda match: json.dumps(json.loads(match.group())), encoded)
    FIXTURE.write_text(encoded + "\n", encoding="utf-8")
    print(f"Wrote {FIXTURE}")
