"""Public traffic-control function API.

Imports are intentionally lazy. ``Global_intersection_coordinate`` imports
the low-level global processor package, so eagerly importing ``global_control``
here would create a circular import during Server_AITC startup.
"""

__all__ = [
    "ControlResult",
    "IntersectionControlRequest",
    "generate_intersection_plan",
    "get_timetable_plan",
    "get_control_function",
    "get_intersection_processing_types",
    "list_control_functions",
    "load_intersection_timetable",
    "process_all_intersections",
    "process_flow_intersections",
    "process_internet_intersections",
    "process_mixed_intersections",
    "validate_control_plan",
]


def __getattr__(name):
    """Resolve public functions only when the caller actually requests them."""
    if name in {"ControlResult", "IntersectionControlRequest"}:
        from .types import ControlResult, IntersectionControlRequest
        return {"ControlResult": ControlResult,
                "IntersectionControlRequest": IntersectionControlRequest}[name]
    if name in {"generate_intersection_plan", "validate_control_plan"}:
        from .dqn_control import generate_intersection_plan, validate_control_plan
        return {"generate_intersection_plan": generate_intersection_plan,
                "validate_control_plan": validate_control_plan}[name]
    if name in {"get_timetable_plan", "load_intersection_timetable"}:
        from .schedule_control import get_timetable_plan, load_intersection_timetable
        return {"get_timetable_plan": get_timetable_plan,
                "load_intersection_timetable": load_intersection_timetable}[name]
    if name in {"get_intersection_processing_types", "process_all_intersections",
                "process_flow_intersections", "process_internet_intersections",
                "process_mixed_intersections"}:
        from . import global_control
        return getattr(global_control, name)
    if name in {"get_control_function", "list_control_functions"}:
        from .registry import get_control_function, list_control_functions
        return {"get_control_function": get_control_function,
                "list_control_functions": list_control_functions}[name]
    raise AttributeError(name)
