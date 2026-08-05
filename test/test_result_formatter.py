import unittest

import Lambdas
from runtime.result_formatter import format_result


class ResultFormatterTest(unittest.TestCase):
    def test_formats_existing_control_message_shape(self):
        result = format_result(
            "1300068",
            [15, 20, 0, 99, 99, 99, 99, 99, 99, "program-1"],
            [3, 4, 5, 6],
            [90, 1, 2, 3, 4, 5, 6, 7],
            lambdas_module=Lambdas,
        )

        self.assertEqual(result["additional"]["tlLogic"]["id"], "1300068")
        self.assertEqual(result["additional"]["tlLogic"]["programID"], "program-1")
        self.assertEqual(
            result["additional"]["tlLogic"]["phase"],
            [{"duration": 15}, {"duration": 20}],
        )
        self.assertEqual(len(result["traffic_vector"]), 4)
        self.assertEqual(result["modelInfo"]["score"], 3)


if __name__ == "__main__":
    unittest.main()
