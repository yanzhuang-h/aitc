"""运行数据校验测试。"""

from __future__ import annotations

import unittest

from infra.data import is_millisecond_timestamp


class MillisecondTimestampTest(unittest.TestCase):
    def test_accepts_numeric_timestamps(self) -> None:
        self.assertTrue(is_millisecond_timestamp(1755588726000))
        self.assertTrue(is_millisecond_timestamp("1755588726000"))

    def test_rejects_missing_or_invalid_timestamps(self) -> None:
        self.assertFalse(is_millisecond_timestamp(None))
        self.assertFalse(is_millisecond_timestamp(""))
        self.assertFalse(is_millisecond_timestamp("not-a-timestamp"))
        self.assertFalse(is_millisecond_timestamp(True))


if __name__ == "__main__":
    unittest.main()
