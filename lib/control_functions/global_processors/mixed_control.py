"""Mixed video/Internet road processing helpers."""

from .internet_state import calculate_internet_direction_demand


def calculate_mixed_direction_demand(direction_state, current_plan, init_add):
    """Combine an existing video plan with Internet congestion adjustments."""
    demand = calculate_internet_direction_demand(
        direction_state,
        [current_plan[2], current_plan[3], current_plan[0], current_plan[1]],
        init_add,
    )
    return {
        **demand,
        "UTL": current_plan[4],
        "DTL": current_plan[5],
        "LTL": current_plan[6],
        "RTL": current_plan[7],
    }


def select_mixed_control_state(direction_state, demand, road_config, hour):
    """Select a mixed-road state before the shared forced-state override."""
    state = "0"
    jam = {key: direction_state[key][3] == 1 for key in "LRUD"}
    compound_rules = (
        ("11", jam["R"] and jam["U"]),
        ("12", jam["L"] and jam["U"]),
        ("13", jam["R"] and jam["D"]),
        ("14", jam["L"] and jam["D"]),
        ("15", jam["R"] and jam["L"]),
        ("16", jam["U"] and jam["D"]),
    )
    for candidate, enabled in compound_rules:
        if enabled and state == "0" and candidate in road_config:
            state = candidate
    differences = [
        demand["R"] - demand["L"], demand["L"] - demand["R"],
        demand["D"] - demand["U"], demand["U"] - demand["D"],
    ]
    maximum, local = 0, "0"
    for index, value in enumerate(differences):
        if str(index + 1) not in road_config:
            continue
        if value > maximum:
            maximum, local = value, str(index + 1)
    if maximum > 15:
        state = local
    if state == "0" and hour < 5 and "5" in road_config:
        state = "5"
    return state


def generate_mixed_phase_plan(plan, demand, state_config):
    """Populate a mixed-road plan and apply legacy per-phase bounds."""
    phases = state_config["phase"]
    minimums = state_config["platform_min_pass_time"]
    maximums = state_config["max_pass_time"]
    marks = {name: -1 for name in ("L", "R", "U", "D", "LR", "UD")}
    for index, phase_type in enumerate(phases[:8]):
        if phase_type in marks:
            marks[phase_type] = index

    l, r, u, d = (demand[key] for key in ("L", "R", "U", "D"))
    for index, phase_type in enumerate(phases[:8]):
        value = None
        if phase_type == "UD":
            if marks["U"] == -1 and marks["D"] == -1: value = max(u, d)
            elif marks["U"] != -1 and marks["D"] != -1: value = min(u, d) - 10
            else: value = min(u, d)
        elif phase_type == "LR":
            if marks["L"] == -1 and marks["R"] == -1: value = max(l, r)
            elif marks["L"] != -1 and marks["R"] != -1: value = min(l, r) - 10
            else: value = min(l, r)
        elif phase_type == "LRL": value = max(demand["LTL"], demand["RTL"])
        elif phase_type == "UDL": value = max(demand["UTL"], demand["DTL"])
        elif phase_type == "L":
            value = max(max(l-r, 0)+10, 15) if marks["R"] != -1 and marks["LR"] != -1 else (max(l-r, 15) if marks["LR"] != -1 else l)
        elif phase_type == "R":
            value = max(max(r-l, 0)+10, 15) if marks["L"] != -1 and marks["LR"] != -1 else (max(r-l, 15) if marks["LR"] != -1 else r)
        elif phase_type == "U":
            value = max(max(u-d, 0)+10, 15) if marks["D"] != -1 and marks["UD"] != -1 else (max(u-d, 15) if marks["UD"] != -1 else u)
        elif phase_type == "D":
            value = max(max(d-u, 0)+10, 15) if marks["U"] != -1 and marks["UD"] != -1 else (max(d-u, 15) if marks["UD"] != -1 else d)
        if value is not None:
            plan[index] = max(min(value, maximums[index]), minimums[index])
        elif phase_type == "P":
            plan[index] = sum(plan[:10]) * 0.25 + minimums[index]
    return plan


def process_mixed_intersection(cross_id, current_plan, direction_state,
                               road_config, hour, init_add,
                               forced_state_selector, schedule_loader,
                               force_process=False):
    """Run the complete legacy mixed-road branch for one intersection."""
    report = {"success": False, "cross_id": str(cross_id), "state": None,
              "fallback": None, "error": None}
    try:
        plan = current_plan
        if plan == [0] * 10:
            plan = schedule_loader(int(cross_id))[str(hour)]
            report["fallback"] = "time_schedule"
            if not force_process:
                report["success"] = True
                return plan, report

        demand = calculate_mixed_direction_demand(
            direction_state, plan, init_add
        )
        for index in range(8):
            plan[index] = 0
        state = select_mixed_control_state(
            direction_state, demand, road_config, hour
        )
        state = forced_state_selector(str(cross_id), state)
        generate_mixed_phase_plan(plan, demand, road_config[state])
        plan[9] = int(state)
        report.update({"success": True, "state": state})
        return plan, report
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        try:
            plan = schedule_loader(int(cross_id))[str(hour)]
            report["fallback"] = "time_schedule_after_error"
            return plan, report
        except Exception:
            return current_plan, report

