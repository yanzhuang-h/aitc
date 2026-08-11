"""Internet-road observation aggregation for global intersection control."""


def update_internet_road_state(state, online_data_map, internet_road_ids,
                               online_map_info):
    """Initialize and update Internet-derived directional road state.

    Args:
        state: Mutable mapping keyed by integer intersection ID. Each direction
            (``L``, ``R``, ``U``, ``D``) stores five legacy slots:
            ``[sample_count, congested_count, average_speed, jam_flag, reserved]``.
            Existing IDs outside ``internet_road_ids`` are preserved exactly.
        online_data_map: ``{road_segment_id: {timestamp: [observation, ...]}}``.
            An observation needs ``jam_state_no`` and ``speed`` fields. Invalid
            records retain the historical behavior of being skipped.
        internet_road_ids: Iterable of integer intersection IDs to initialize.
        online_map_info: Existing road-segment to intersection-direction mapping.

    Returns:
        The same mutable ``state`` object after update. This preserves the legacy
        global-state semantics while making the data aggregation callable alone.

    Notes:
        The formulas and broad invalid-record skipping intentionally match the
        original ``coordinate()`` implementation. No control plan is generated
        here and no input control plan is modified.
    """
    for cross_id in internet_road_ids:
        state[cross_id] = {
            "L": [0, 0, 20, 0, 0],
            "R": [0, 0, 20, 0, 0],
            "U": [0, 0, 20, 0, 0],
            "D": [0, 0, 20, 0, 0],
        }

    for road_segment_id in online_data_map:
        try:
            if road_segment_id not in online_map_info:
                continue
            observation_times = sorted(online_data_map[road_segment_id].keys())
            for observation_time in observation_times:
                observation = online_data_map[road_segment_id][observation_time][0]
                for cross_id in online_map_info[road_segment_id]:
                    direction = online_map_info[road_segment_id][cross_id]
                    if direction not in state[cross_id]:
                        continue
                    direction_state = state[cross_id][direction]
                    if observation["jam_state_no"] != 0:
                        direction_state[1] += 1
                        direction_state[3] = 1
                    else:
                        direction_state[3] = 0
                    direction_state[2] = (direction_state[2] + observation["speed"]) / 2
                    direction_state[0] += 1
        except Exception:
            # Compatibility: malformed external Internet records never abort a
            # complete control round in the existing global implementation.
            continue
    return state


def calculate_internet_direction_demand(direction_state, fine_row, init_add):
    """Calculate L/R/U/D demand from one Internet road-state snapshot.

    Args:
        direction_state: Directional legacy state with ``L``, ``R``, ``U`` and
            ``D`` entries in the five-slot format returned by
            :func:`update_internet_road_state`.
        fine_row: Four numeric baseline values for the current local hour in
            legacy ``[L, R, U, D]`` order.
        init_add: Existing adjustment function (currently ``Init_add``), passed
            in to preserve its exact road-state formula.

    Returns:
        dict[str, float]: Direction demands keyed by ``L``, ``R``, ``U``, ``D``.
        The congestion penalties and cross-direction reductions exactly preserve
        the previous inlined Internet-control calculation.
    """
    l_mark = r_mark = u_mark = d_mark = 0
    try:
        l_add = init_add(direction_state["L"])
        r_add = init_add(direction_state["R"])
        u_add = init_add(direction_state["U"])
        d_add = init_add(direction_state["D"])
    except Exception:
        l_add = r_add = u_add = d_add = 0

    if direction_state["L"][3] == 1:
        l_add += 15
        u_mark = d_mark = -1
    if direction_state["R"][3] == 1:
        r_add += 15
        u_mark = d_mark = -1
    if direction_state["U"][3] == 1:
        u_add += 15
        l_mark = r_mark = -1
    if direction_state["D"][3] == 1:
        d_add += 15
        l_mark = r_mark = -1

    if l_mark == -1:
        l_add -= 8
    if r_mark == -1:
        r_add -= 8
    if u_mark == -1:
        u_add -= 8
    if d_mark == -1:
        d_add -= 8

    return {
        "L": max(fine_row[0] + l_add, 0),
        "R": max(fine_row[1] + r_add, 0),
        "U": max(fine_row[2] + u_add, 0),
        "D": max(fine_row[3] + d_add, 0),
    }


def select_internet_control_state(cross_id, direction_demand, road_config,
                                  hour, peak_hours=None):
    """Return the legacy Internet state selected from directional demand."""
    left, right = direction_demand["L"], direction_demand["R"]
    up, down = direction_demand["U"], direction_demand["D"]
    differences = [right-left, left-right, down-up, up-down] + [0] * 17
    maximum, local_state = 0, "0"
    for index in range(4):
        if str(index + 1) not in road_config:
            differences[index] = 0
        if differences[index] > maximum:
            local_state, maximum = str(index + 1), differences[index]
    state = "0"
    if cross_id == "1300360" and str(hour) in (peak_hours or {}).get(cross_id, ()):
        state = "16"
    if cross_id == "1300306" and 6 <= hour <= 8:
        state = "21"
    if cross_id == "1300318" and 6 <= hour < 9:
        state = "2"
    if state == "0":
        if right-left >= 15 and up-down >= 15: differences[11] = 100
        if left-right >= 15 and up-down >= 15: differences[12] = 100
        if right-left >= 15 and down-up >= 15: differences[13] = 100
        if left-right >= 15 and down-up >= 15: differences[14] = 100
        for index in range(20):
            if str(index) not in road_config: differences[index] = 0
            if differences[index] > maximum:
                local_state, maximum = str(index), differences[index]
    if maximum >= 15: state = local_state
    if state == "0" and hour < 5 and "5" in road_config: state = "5"
    if cross_id == "1300318" and state != "5" and hour >= 9: state = "0"
    return state


def apply_internet_phase_demand(plan, phase_types, phase_weights, demand):
    """Apply Internet directional demand to an existing eight-phase plan."""
    l, r, u, d = (demand[key] for key in ("L", "R", "U", "D"))
    marks = {name: -1 for name in ("L", "R", "U", "D", "LR", "UD")}
    for index, phase_type in enumerate(phase_types[:8]):
        if phase_type in marks:
            marks[phase_type] = index
    for index, phase_type in enumerate(phase_types[:8]):
        if phase_type == "UD":
            extra = (max(d-u, 0) if marks["D"] == -1 else 0) + (max(u-d, 0) if marks["U"] == -1 else 0)
            plan[index] += min(u, d) + extra
        elif phase_type == "UD2":
            extra = (max(d-u, 0) if marks["D"] == -1 else 0) + (max(u-d, 0) if marks["U"] == -1 else 0)
            plan[index] += int((min(u, d) + extra) / 2)
        elif phase_type in ("LR", "LR2"):
            extra = (max(l-r, 0) if marks["L"] == -1 else 0) + (max(r-l, 0) if marks["R"] == -1 else 0)
            value = min(l, r) + extra
            plan[index] += value if phase_type == "LR" else int(value / 2)
        elif phase_type in ("LRL", "LRL2"):
            plan[index] += max(l, r) * (0.3 if phase_type == "LRL" else 0.15) * phase_weights[index]
        elif phase_type in ("UDL", "UDL2"):
            plan[index] += max(u, d) * (0.3 if phase_type == "UDL" else 0.15) * phase_weights[index]
        elif phase_type == "L":
            plan[index] += l if marks["LR"] == -1 else max(l-r, 0)
        elif phase_type == "R":
            plan[index] += r if marks["LR"] == -1 else max(r-l, 0)
        elif phase_type == "U":
            plan[index] += u if marks["UD"] == -1 else max(u-d, 0)
        elif phase_type == "D":
            plan[index] += d if marks["UD"] == -1 else max(d-u, 0)
    return plan
