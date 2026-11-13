"""Shared final plan value finalization."""
import json
import logging
from lib.floating_value import apply_floating_value
from lib.road_groups import TONGZHOU_49, road_group
from .phase_adapter import phase_bounds, complete_phase_cycle

LOGGER = logging.getLogger("FlowControl")


def finalize_plan_values(result_action_map, *, road_info=None):
    """Preserve integer conversion followed by floating-value application."""
    for plan in result_action_map.values():
        for index in range(len(plan)):
            plan[index] = int(plan[index])
    result_action_map, report = apply_floating_value(result_action_map, return_report=True)
    if road_info is not None:
        for cross_id, plan in result_action_map.items():
            if str(cross_id) not in TONGZHOU_49:
                continue
            config = road_info[str(cross_id)][str(plan[9])]
            phases, lows, highs = phase_bounds(config)
            times, audit = complete_phase_cycle(plan[:len(phases)], lows, highs)
            plan[:8] = times + [0] * (8-len(times))
            LOGGER.info("flow_control_final %s", json.dumps({
                "cross_id": str(cross_id), "road_group": road_group(cross_id),
                "state": str(plan[9]), "phase_names": phases,
                "output_phase_vector": list(plan), "is_final": True, **audit,
            }, separators=(",", ":")))
    return result_action_map, report


def complete_minimum_cycle(result_action_map):
    """Preserve legacy 60-second minimum-cycle completion."""
    for cross_id, plan in result_action_map.items():
        if str(cross_id) in TONGZHOU_49:
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
