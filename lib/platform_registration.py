"""由接入记录和现有路口配置推导新平台路口。"""

def registered_platform_programs(settings):
    """整数条目仍是既有方案号覆盖；对象条目是新平台路口登记。"""
    return {road: entry["program_id"] for road, entry in settings.items()
            if isinstance(entry, dict) and "program_id" in entry}


def platform_additions(programs, existing, cross_info, road_info, detectors, aliases):
    from lib.control_functions.global_processors.phase_adapter import phase_bounds
    from lib.cross_info_functions import _normalize_cross_info

    additions, issues = {}, {}
    resolved_detectors = dict(detectors)
    for road in sorted(programs.keys() - set(existing)):
        try:
            if not road.isdecimal() or str(int(road)) != road:
                raise ValueError("路口编号须使用不带前导零的数字")
            if type(programs[road]) is not int or programs[road] < 0:
                raise ValueError("默认方案号须为非负整数")
            cross = _normalize_cross_info({"cross_info": cross_info.get(road)})
            phase_bounds(road_info[road][str(programs[road])])
            mapping = {int(detector): (road, direction) for detector, direction in cross["jtll_ddbh"].items()}
            for detector, new in mapping.items():
                if detector in resolved_detectors:
                    owner, direction = resolved_detectors[detector]
                    if (str(aliases.get(str(owner), owner)), direction) != new:
                        raise ValueError(f"检测器 {detector} 已映射至 {owner}/{direction}")
        except (KeyError, TypeError, ValueError) as error:
            issues[road] = str(error)
            continue
        additions[road] = mapping
        resolved_detectors.update(mapping)
    return additions, issues
