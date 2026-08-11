"""Single-intersection plan generation for pure Internet roads."""

from .internet_state import (
    apply_internet_phase_demand,
    calculate_internet_direction_demand,
    select_internet_control_state,
)


def process_internet_intersection(cross_id, direction_state, fine_row,
                                  road_config, hour, init_add,
                                  forced_state_selector, peak_hours=None):
    """Generate one legacy-compatible Internet intersection plan.

    Returns ``(plan, report)``. The plan is ``None`` on failure so the caller
    can preserve the historical behavior of leaving its existing plan intact.
    """
    report = {
        "success": False,
        "cross_id": str(cross_id),
        "source": "internet_single_control",
        "state": None,
        "direction_demand": None,
        "warnings": [],
        "error": None,
    }
    try:
        demand = calculate_internet_direction_demand(
            direction_state, fine_row, init_add
        )
        state = select_internet_control_state(
            str(cross_id), demand, road_config, int(hour), peak_hours
        )
        state = forced_state_selector(str(cross_id), state)
        state_config = road_config[state]

        # Preserve legacy aliasing: the old coordinator mutates this list from
        # the per-round road_info mapping instead of copying it.
        plan = state_config["min_pass_time"]
        apply_internet_phase_demand(
            plan,
            state_config["phase"],
            state_config["phase_weight"],
            demand,
        )
        plan[9] = int(state)
        report.update({
            "success": True,
            "state": state,
            "direction_demand": demand,
        })
        return plan, report
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return None, report
