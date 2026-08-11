"""Shared final plan value finalization."""
from lib.floating_value import apply_floating_value


def finalize_plan_values(result_action_map):
    """Preserve integer conversion followed by floating-value application."""
    for plan in result_action_map.values():
        for index in range(len(plan)):
            plan[index] = int(plan[index])
    result_action_map, report = apply_floating_value(result_action_map, return_report=True)
    return result_action_map, report


def complete_minimum_cycle(result_action_map):
    """Preserve legacy 60-second minimum-cycle completion."""
    for plan in result_action_map.values():
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
