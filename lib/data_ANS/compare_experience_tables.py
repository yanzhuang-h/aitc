"""Compare two experience tables using the shared movement lane policy."""

import argparse
import json
from pathlib import Path
import sys

try:
    from lib.data_ANS.lane_policy import (
        LANE_COUNT,
        configured_movement_lane_policy,
        normalize_lane_type,
    )
except ModuleNotFoundError:  # Supports direct execution from this directory.
    from lane_policy import (
        LANE_COUNT,
        configured_movement_lane_policy,
        normalize_lane_type,
    )


BASE_DIRECTIONS = ("U", "D", "L", "R")
LEFT_DIRECTIONS = ("UTL", "DTL", "LTL", "RTL")
ALL_DIRECTIONS = BASE_DIRECTIONS + LEFT_DIRECTIONS
DEFAULT_ROAD_IDS = ("1300069", "1300068", "1700125")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TABLE1_PATH = PROJECT_ROOT / "lib" / "lin_shi_11123.json"
DEFAULT_TABLE2_PATH = (
    PROJECT_ROOT
    / "logs_data"
    / "training_results"
    / "lin_shi_11123_3roads_monotone_buqi.json"
)
DEFAULT_CROSS_INFO_PATH = PROJECT_ROOT / "lib" / "cross_info.json"


def load_json(path):
    path = Path(path)
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return data


def normalize_flow_vector(values):
    result = [0] * LANE_COUNT
    if not isinstance(values, (list, tuple)):
        return result
    for index, value in enumerate(values[:LANE_COUNT]):
        try:
            result[index] = int(round(float(value)))
        except (TypeError, ValueError):
            result[index] = 0
    return result


def movement_lane_details(cross_info, road_id, direction):
    road_id = str(road_id)
    cross_config = cross_info.get(road_id, {})
    selection = configured_movement_lane_policy(
        cross_config,
        direction,
        LANE_COUNT,
    )
    lane_map = cross_config.get("LaneNo", {}).get(direction[0], {})
    return [
        {
            "lane": lane,
            "lane_type": normalize_lane_type(
                lane_map.get(str(lane), lane_map.get(lane))
            ),
        }
        for lane in sorted(selection["eligible"])
    ]


def movement_total(values, lane_details):
    if values is None:
        return None
    vector = normalize_flow_vector(values)
    return sum(vector[item["lane"]] for item in lane_details)


def direction_times(direction_data1, direction_data2):
    times = set()
    for direction_data in (direction_data1, direction_data2):
        if not isinstance(direction_data, dict):
            continue
        for raw_time in direction_data:
            try:
                times.add(int(raw_time))
            except (TypeError, ValueError):
                continue
    return sorted(times)


def time_vector(direction_data, green_time):
    if not isinstance(direction_data, dict):
        return None
    if str(green_time) in direction_data:
        return direction_data[str(green_time)]
    return direction_data.get(green_time)


def _format_value(value):
    return "-" if value is None else str(value)


def _lane_label(direction, lane_details):
    lane_text = ", ".join(
        f"{item['lane']}({item['lane_type']})"
        for item in lane_details
    )
    if direction in LEFT_DIRECTIONS:
        return f"1A left lanes: {lane_text}"
    return f"controlled base lanes: {lane_text}"


def print_direction_compare(
    road_id,
    direction,
    road_data1,
    road_data2,
    cross_info,
    table1_label,
    table2_label,
    output,
):
    direction_data1 = road_data1.get(direction, {})
    direction_data2 = road_data2.get(direction, {})
    times = direction_times(direction_data1, direction_data2)
    if not times:
        return

    lane_details = movement_lane_details(cross_info, road_id, direction)
    print(f"\nDirection {direction}", file=output)
    if not lane_details:
        if direction in LEFT_DIRECTIONS:
            print("  no configured capacity-eligible 1A lane", file=output)
        else:
            print("  no configured controlled base lane", file=output)
        return

    print(f"  {_lane_label(direction, lane_details)}", file=output)
    print(
        f"{'time':>6}  {table1_label:>18}  {table2_label:>18}  {'diff':>8}",
        file=output,
    )
    for green_time in times:
        value1 = movement_total(
            time_vector(direction_data1, green_time),
            lane_details,
        )
        value2 = movement_total(
            time_vector(direction_data2, green_time),
            lane_details,
        )
        difference = (
            value2 - value1
            if value1 is not None and value2 is not None
            else None
        )
        print(
            f"{green_time:>6}  {_format_value(value1):>18}  "
            f"{_format_value(value2):>18}  {_format_value(difference):>8}",
            file=output,
        )


def print_road_compare(
    road_id,
    table1,
    table2,
    cross_info,
    table1_label,
    table2_label,
    output=sys.stdout,
):
    road_id = str(road_id)
    road_data1 = table1.get(road_id)
    road_data2 = table2.get(road_id)
    if not isinstance(road_data1, dict) or not isinstance(road_data2, dict):
        missing = []
        if not isinstance(road_data1, dict):
            missing.append(table1_label)
        if not isinstance(road_data2, dict):
            missing.append(table2_label)
        print(f"Road {road_id}: missing in {', '.join(missing)}", file=output)
        return

    print("=" * 92, file=output)
    print(f"Road {road_id}", file=output)
    print(f"Table 1: {table1_label}", file=output)
    print(f"Table 2: {table2_label}", file=output)
    for direction in ALL_DIRECTIONS:
        print_direction_compare(
            road_id,
            direction,
            road_data1,
            road_data2,
            cross_info,
            table1_label,
            table2_label,
            output,
        )
    print(file=output)


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Compare base-direction controlled-lane totals and dedicated "
            "left-turn 1A-lane totals between two experience tables."
        )
    )
    parser.add_argument("--table1", type=Path, default=DEFAULT_TABLE1_PATH)
    parser.add_argument("--table2", type=Path, default=DEFAULT_TABLE2_PATH)
    parser.add_argument(
        "--cross-info",
        type=Path,
        default=DEFAULT_CROSS_INFO_PATH,
    )
    parser.add_argument(
        "--roads",
        nargs="+",
        default=list(DEFAULT_ROAD_IDS),
    )
    return parser


def main(argv=None):
    args = build_argument_parser().parse_args(argv)
    table1 = load_json(args.table1)
    table2 = load_json(args.table2)
    cross_info = load_json(args.cross_info)

    for road_id in args.roads:
        print_road_compare(
            road_id,
            table1,
            table2,
            cross_info,
            args.table1.stem,
            args.table2.stem,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
