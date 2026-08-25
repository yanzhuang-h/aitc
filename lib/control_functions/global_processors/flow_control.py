"""Pure-flow intersection state selection."""


def select_flow_control_state(cross_id, demand, road_config, hour):
    differences = [demand["R"] - demand["L"], demand["L"] - demand["R"], demand["D"] - demand["U"], demand["U"] - demand["D"]]
    state, maximum = "0", 0
    for index, value in enumerate(differences):
        if str(index + 1) in road_config and value > maximum:
            state, maximum = str(index + 1), value
    if maximum > 15:
        return state
    if hour < 5 and "5" in road_config:
        state = "5"
    # 与 V2.65 保持一致：部分路口的高峰强制状态带尾逗号（tuple）。
    # tuple 在后续 road_config[state] 查表时会抛 KeyError，整体回退到
    # 时段表方案（Get_time_map），这正是 V2.65 的原始行为，不能去掉。
    overrides = {
        "1700079": (((7, 9), "21"), ((16, 19), "16")),
        "1300306": (((7, 8), "21"), ((17, 18), "21")),
        "1700293": (((6, 6), "23"), ((7, 9), "22"), ((16, 19), "21")),
        "2702736": (((16, 19), ("21",)),),
        "1300255": (((6, 8), ("21",)),),
        "1300364": (((7, 8), ("4",)), ((16, 18), ("4",))),
        "1700124": (((7, 8), ("21",)), ((16, 19), ("21",))),
        "1300039": (((7, 8), ("2",)),),
        "1300108": (((16, 19), ("1",)),),
        "1300120": (((8, 11), ("2",)),),
    }
    for window, value in overrides.get(str(cross_id), ()):
        if window[0] <= hour <= window[1]:
            state = value
    return state


def generate_flow_phase_plan(plan, demand, state_config):
    """Generate flow phases using the legacy dedicated half-phase rules."""
    phases = state_config["phase"]
    mins, maxs = state_config["platform_min_pass_time"], state_config["max_pass_time"]
    marks = {name: -1 for name in ("L", "R", "U", "D", "LR", "UD")}
    for i, name in enumerate(phases[:8]):
        if name in marks: marks[name] = i
    l, r, u, d = (demand[k] for k in ("L", "R", "U", "D"))
    for i, name in enumerate(phases[:8]):
        if name == "UD": value = max(u, d) if marks["U"] == marks["D"] == -1 else min(u, d) - (10 if marks["U"] != -1 and marks["D"] != -1 else 0)
        elif name in ("UD1", "UD2"): value = max(u, d) // 2
        elif name == "LR": value = max(l, r) if marks["L"] == marks["R"] == -1 else min(l, r) - (10 if marks["L"] != -1 and marks["R"] != -1 else 0)
        elif name in ("LR1", "LR2"): value = max(l, r) // 2
        elif name == "LRL": value = max(demand["LTL"], demand["RTL"]) + max(l, r) * .05
        elif name == "UDL": value = max(demand["UTL"], demand["DTL"]) + max(u, d) * .05
        elif name == "L": value = max(max(l-r, 0)+10, 15) if marks["R"] != -1 and marks["LR"] != -1 else (max(l-r, 15) if marks["LR"] != -1 else l)
        elif name == "R": value = max(max(r-l, 0)+10, 15) if marks["L"] != -1 and marks["LR"] != -1 else (max(r-l, 15) if marks["LR"] != -1 else r)
        elif name in ("U", "D"):
            own, other, other_mark = (u, d, marks["D"]) if name == "U" else (d, u, marks["U"])
            value = max(max(u-d, 0)+10, 15, max(d-u, 0)+10) if other_mark != -1 and marks["UD"] != -1 else (max(own-other, 15) if marks["UD"] != -1 else own)
        elif name == "P":
            plan[i] = sum(plan[:10]) * .25 + mins[i]
            continue
        else: continue
        plan[i] = max(min(value, maxs[i]), mins[i])
    return plan


def process_flow_intersection(cross_id, current_plan, road_config, hour,
                              forced_state_selector, schedule_loader):
    """Run one complete pure-flow intersection branch."""
    report = {"success": False, "cross_id": str(cross_id), "state": None,
              "fallback": None, "error": None}
    try:
        if current_plan == [0] * 10:
            plan = schedule_loader(int(cross_id))[str(hour)]
            report.update({"success": True, "fallback": "time_schedule"})
            return plan, report
        demand = {"L": max(current_plan[2], 0), "R": max(current_plan[3], 0),
                  "U": max(current_plan[0], 0), "D": max(current_plan[1], 0),
                  "UTL": current_plan[4], "DTL": current_plan[5],
                  "LTL": current_plan[6], "RTL": current_plan[7]}
        for index in range(8):
            current_plan[index] = 0
        state = select_flow_control_state(cross_id, demand, road_config, hour)
        state = forced_state_selector(str(cross_id), state)
        generate_flow_phase_plan(current_plan, demand, road_config[state])
        current_plan[9] = int(state)
        report.update({"success": True, "state": state})
        return current_plan, report
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        # 与 V2.65 的内层 try/except 语义一致：状态计算或相位生成
        # 异常时保持当前 plan（已清零，交由后续最小周期等公共处理），
        # 不在这里回退时段表。
        return current_plan, report
