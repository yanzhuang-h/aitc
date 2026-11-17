"""Shared final plan value finalization."""
import json
import logging
from infra.logging import decision_batch_id
from lib.floating_value import apply_floating_value
from lib.road_groups import road_group
from lib.intersection_strategy import uses_platform_phase_timing
from .phase_adapter import phase_bounds, complete_phase_cycle

LOGGER = logging.getLogger("FlowControl")


def finalize_plan_values(result_action_map, *, road_info=None):
    """Preserve integer conversion followed by floating-value application."""
    for plan in result_action_map.values():
        for index in range(len(plan)):
            plan[index] = int(plan[index])
    before_floating = {str(road): list(plan) for road, plan in result_action_map.items()
                       if road_group(road) is not None or uses_platform_phase_timing(road)}
    result_action_map, report = apply_floating_value(result_action_map, return_report=True)
    if road_info is not None:
        for cross_id, plan in result_action_map.items():
            group = road_group(cross_id)
            platform_strategy = uses_platform_phase_timing(cross_id)
            if group is None and not platform_strategy:
                continue
            after_floating = list(plan)
            if platform_strategy:
                config = road_info[str(cross_id)][str(plan[9])]
                phases, lows, highs = phase_bounds(config)
                times, audit = complete_phase_cycle(plan[:len(phases)], lows, highs)
                plan[:8] = times + [0] * (8-len(times))
            else:
                # 19组只补齐协调后的记录，沿用原配时，不套用49组边界规则。
                config = road_info.get(str(cross_id), {}).get(str(plan[9]), {})
                phases = list(config.get("phase", [])[:8])
                audit = {}
            LOGGER.info("flow_control_final %s", json.dumps({
                "cross_id": str(cross_id), "road_group": group,
                "batch_id": decision_batch_id.get(),
                "stage": "coordinator_finalization",
                "before_floating": before_floating[str(cross_id)],
                "after_floating_before_bounds": after_floating,
                "selected_program": {key: config[key] for key in (
                    "phase", "min_pass_time", "max_pass_time",
                    "platform_min_pass_time", "platform_max_pass_time") if key in config},
                "bounded_phase_changes": [
                    {"index": i, "before": after_floating[i], "after": plan[i]}
                    for i in range(min(8, len(plan))) if after_floating[i] != plan[i]
                ],
                "state": str(plan[9]), "phase_names": phases,
                "output_phase_vector": list(plan), "is_final": True, **audit,
            }, separators=(",", ":")))
    return result_action_map, report


def complete_minimum_cycle(result_action_map):
    """Preserve legacy 60-second minimum-cycle completion."""
    for cross_id, plan in result_action_map.items():
        if uses_platform_phase_timing(cross_id):
            continue
        total = sum(plan[:5])
        if total < 60:
            add = 60 - total
            active = sum(1 for value in plan[:6] if value != 0)
            if active:
                for index in range(6):
                    if plan[index] != 0:
                        plan[index] += int(add / active)
        total = sum(plan[:5])
        if total < 60 and plan[0] != 0:
            plan[0] += 60 - total
    return result_action_map
