"""Shared lane-type policy for training, feedback, lookup, and release."""

LANE_POLICY_VERSION = "1.0"
LANE_COUNT = 10
BASE_DIRECTIONS = ("U", "D", "L", "R")
DEDICATED_LEFT_TURN_LANE_TYPE = "1A"


LANE_TYPE_RULES = {
    "1A": {
        "movement": "left",
        "experience_group": "dedicated_left",
        "control": "signal_controlled",
        "capacity_eligible": True,
        "shared": False,
    },
    "1B": {
        "movement": "straight",
        "experience_group": "base",
        "control": "signal_controlled",
        "capacity_eligible": True,
        "shared": False,
    },
    "1C": {
        "movement": "right",
        "experience_group": "base",
        "control": "uncontrolled",
        "capacity_eligible": False,
        "shared": False,
    },
    "1D": {
        "movement": "uturn",
        "experience_group": "base",
        "control": "signal_or_layout_dependent",
        "capacity_eligible": True,
        "shared": False,
    },
    "2A": {
        "movement": "straight_left",
        "experience_group": "base",
        "control": "signal_controlled",
        "capacity_eligible": True,
        "shared": True,
    },
    "2B": {
        "movement": "straight_right",
        "experience_group": "base",
        "control": "signal_controlled",
        "capacity_eligible": True,
        "shared": True,
    },
    "2C": {
        "movement": "left_uturn",
        "experience_group": "base",
        "control": "signal_or_layout_dependent",
        "capacity_eligible": True,
        "shared": True,
    },
    "3A": {
        "movement": "unrestricted",
        "experience_group": "base",
        "control": "uncontrolled",
        "capacity_eligible": False,
        "shared": True,
    },
    "3B": {
        "movement": "project_extension_unverified",
        "experience_group": "base",
        "control": "unverified",
        "capacity_eligible": False,
        "shared": True,
    },
}


def normalize_lane_type(lane_type):
    return str(lane_type or "").strip().upper()


def classify_lane_type(lane_type):
    normalized = normalize_lane_type(lane_type)
    rule = LANE_TYPE_RULES.get(normalized)
    if rule is None:
        rule = {
            "movement": "unknown",
            "experience_group": "base",
            "control": "unverified",
            "capacity_eligible": False,
            "shared": False,
        }
    result = dict(rule)
    result.update({
        "lane_type": normalized,
        "known": normalized in LANE_TYPE_RULES,
    })
    return result


def is_dedicated_left(lane_type):
    return normalize_lane_type(lane_type) == DEDICATED_LEFT_TURN_LANE_TYPE


def raw_movement_direction(base_direction, lane_type):
    base_direction = str(base_direction).upper()
    if base_direction not in BASE_DIRECTIONS:
        return None
    if is_dedicated_left(lane_type):
        return base_direction + "TL"
    return base_direction


def capacity_experience_direction(base_direction, lane_type):
    policy = classify_lane_type(lane_type)
    if not policy["capacity_eligible"]:
        return None
    return raw_movement_direction(base_direction, lane_type)


def configured_movement_lane_policy(cross_config, direction, lane_count=LANE_COUNT):
    """Return eligible and excluded configured lanes for one experience direction."""
    direction = str(direction).upper()
    if direction not in BASE_DIRECTIONS and not (
        direction.endswith("TL") and direction[0] in BASE_DIRECTIONS
    ):
        return {"eligible": set(), "excluded": {}, "configured": set()}

    lane_map = cross_config.get("LaneNo", {}).get(direction[0], {})
    eligible = set()
    excluded = {}
    configured = set()
    for raw_lane, lane_type in lane_map.items():
        try:
            lane = int(raw_lane)
        except (TypeError, ValueError):
            continue
        if not 0 <= lane < int(lane_count):
            continue
        if raw_movement_direction(direction[0], lane_type) != direction:
            continue
        configured.add(lane)
        policy = classify_lane_type(lane_type)
        if policy["capacity_eligible"]:
            eligible.add(lane)
        else:
            excluded[lane] = policy
    return {
        "eligible": eligible,
        "excluded": excluded,
        "configured": configured,
    }


def capacity_lane_indexes(cross_config, direction, lane_count=LANE_COUNT):
    return configured_movement_lane_policy(
        cross_config,
        direction,
        lane_count,
    )["eligible"]


def mask_capacity_vector(vector, cross_config, direction, lane_count=LANE_COUNT):
    values = list(vector)
    if len(values) != int(lane_count):
        raise ValueError(f"flow vector must contain exactly {lane_count} lanes")
    allowed = capacity_lane_indexes(cross_config, direction, lane_count)
    return [value if index in allowed else 0 for index, value in enumerate(values)]


def policy_metadata():
    excluded_types = sorted(
        lane_type
        for lane_type, rule in LANE_TYPE_RULES.items()
        if not rule["capacity_eligible"]
    )
    return {
        "version": LANE_POLICY_VERSION,
        "dedicated_left_turn_lane_type": DEDICATED_LEFT_TURN_LANE_TYPE,
        "capacity_excluded_lane_types": excluded_types,
        "unknown_lane_type_capacity_eligible": False,
        "raw_flow_preserved_for_excluded_lanes": True,
    }
