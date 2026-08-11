"""Compare the compatibility coordinate entry with the new callable entry."""

import copy
import json
import random
from pathlib import Path

from lib.Global_intersection_coordinate import coordinate
from .global_control import process_all_intersections


def compare_control_snapshot(snapshot_path):
    """Run both non-green-wave entry points against one Server snapshot.

    Args:
        snapshot_path: JSON file created by Server_AITC when
            ``AITC_CONTROL_SNAPSHOT_ENABLED=1``.

    Returns:
        dict: ``equal`` plus differing intersection plans. Inputs are deep-copied
        before each call because the legacy coordinate function updates maps in
        place. This compares the compatibility function and the new public
        `process_all_intersections` wrapper using identical data.
    """
    with Path(snapshot_path).open("r", encoding="utf-8") as snapshot_file:
        snapshot = json.load(snapshot_file)
    required = {
        "coordinate_input",
        "coordinate_map_set",
        "online_map",
        "overflow_map",
        "extend_map",
    }
    missing = required - set(snapshot)
    if missing:
        raise ValueError("snapshot missing fields: " + ", ".join(sorted(missing)))

    args = (
        snapshot["coordinate_input"],
        snapshot["coordinate_map_set"],
        snapshot["online_map"],
        snapshot["overflow_map"],
        snapshot["extend_map"],
    )
    random.seed(0)
    compatibility_result = coordinate(
        *copy.deepcopy(args),
        enabled_processors=None,
        include_green_wave=False,
    )
    random.seed(0)
    public_result = process_all_intersections(*copy.deepcopy(args))
    differences = {}
    all_ids = set(compatibility_result) | set(public_result)
    for cross_id in sorted(all_ids):
        old_plan = compatibility_result.get(cross_id)
        new_plan = public_result.get(cross_id)
        if old_plan != new_plan:
            differences[str(cross_id)] = {
                "compatibility": old_plan,
                "public": new_plan,
            }
    return {
        "snapshot": str(snapshot_path),
        "equal": not differences,
        "difference_count": len(differences),
        "differences": differences,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare_control_snapshot(args.snapshot), ensure_ascii=False, indent=2))
