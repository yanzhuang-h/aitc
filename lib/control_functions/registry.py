"""Machine-readable registry for a future model function caller."""

from .dqn_control import generate_intersection_plan
from .global_control import (
    process_all_intersections,
    process_flow_intersections,
    process_internet_intersections,
    process_mixed_intersections,
)
from .schedule_control import get_timetable_plan


CONTROL_FUNCTIONS = {
    "generate_intersection_plan": generate_intersection_plan,
    "process_internet_intersections": process_internet_intersections,
    "process_mixed_intersections": process_mixed_intersections,
    "process_flow_intersections": process_flow_intersections,
    "process_all_intersections": process_all_intersections,
    "get_timetable_plan": get_timetable_plan,
}


def list_control_functions():
    """Return callable names and their documented business purpose."""
    return {
        name: {
            "name": name,
            "description": (function.__doc__ or "").strip().splitlines()[0],
        }
        for name, function in CONTROL_FUNCTIONS.items()
    }


def get_control_function(name):
    """Return a registered callable by exact name; raise KeyError if unknown."""
    return CONTROL_FUNCTIONS[name]
