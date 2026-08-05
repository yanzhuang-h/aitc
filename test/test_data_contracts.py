import unittest

from infra.data.classifier import DataKind, DataSource
from infra.data.contracts import CONTRACTS, validate_contract


class DataContractsTest(unittest.TestCase):
    def test_flow_contract_accepts_minimum_payload(self):
        issues = validate_contract(
            DataKind.FLOW,
            {"ycsb_xsfx": "L", "jtll_ddbh": "1", "ycsb_cdbh": "0", "ts": "1700000000000"},
            DataSource.TCP,
        )
        self.assertEqual(issues, [])

    def test_contract_reports_missing_field_invalid_timestamp_and_source(self):
        issues = validate_contract(DataKind.QUEUE, {"jtll_ddbh": "1", "start_time": "bad"}, DataSource.HTTP)
        self.assertIn("来源不符合契约: http", issues)
        self.assertIn("缺少字段: car_nums", issues)
        self.assertIn("时间字段不是整数时间戳: start_time", issues)

    def test_every_runtime_kind_has_expected_contract_or_history_fallback(self):
        self.assertIn(DataKind.RADAR_EVENT, CONTRACTS)
        self.assertNotIn(DataKind.HISTORY, CONTRACTS)


if __name__ == "__main__":
    unittest.main()
