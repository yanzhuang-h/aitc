import unittest
from collections import defaultdict

from lib.control_functions.global_processors.special_intersections import (
    apply_special_intersection_adjustments,
)


def _plan():
    return [0] * 10


def _direction_state():
    return defaultdict(lambda: [0, 0, 0, 0, 0])


class SpecialIntersectionAdjustmentTests(unittest.TestCase):
    def _apply(self, plans, intersection_state=None, forced_roads=None):
        schedule = {str(hour): [10, 10, 10, 0, 0, 0, 0, 0, 0, 0]
                    for hour in range(24)}
        return apply_special_intersection_adjustments(
            plans,
            intersection_state or {},
            forced_roads or set(),
            {},
            {},
            defaultdict(_direction_state),
            defaultdict(lambda: {"s1": 0, "s2": 0}),
            12,
            lambda _cross_id: schedule,
            lambda *_args: (0, 0),
        )

    def test_applies_fixed_special_intersection_adjustments(self):
        plans = defaultdict(_plan)
        plans["1700125"] = [10] + [0] * 9
        plans["1300094"] = [0, 0, 20, 30] + [0] * 6

        result = self._apply(plans, {1700125: {}})

        self.assertEqual(result["1700125"][0], 55)
        self.assertEqual(result["1300094"][2:4], [30, 40])

    def test_forced_aibi_road_skips_1300870_state_rewrite(self):
        plans = defaultdict(_plan)
        plans["1300870"] = [40, 30, 0, 0, 0, 0, 0, 0, 0, 0]
        state = _direction_state()
        state["U"] = [1, 2, 20, 1, 0]
        state["D"] = [1, 2, 20, 0, 0]

        result = self._apply(
            plans,
            {1300870: state},
            {1300870},
        )

        self.assertEqual(result["1300870"], [40, 30, 0, 0, 0, 0, 0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
