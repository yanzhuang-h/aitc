"""运行数据仓库的独立行为测试。"""

from __future__ import annotations

import tempfile
import unittest

from infra.data import (
    ConfigService,
    DataKind,
    LongTermMemory,
    ResultWarehouse,
    ShortTermMemory,
    MemoryQueryLayer,
    RuntimeDataReceiver,
    DataQualityMonitor,
)


class _MemoryWriter:
    def __init__(self) -> None:
        self.records: list[tuple[DataKind, dict]] = []

    def write(self, kind: DataKind, data: dict) -> None:
        self.records.append((kind, data))


class _Lambdas:
    location_to_intersection_lambda = {1: ("1300068", "U")}


class RuntimeRepositoryTest(unittest.TestCase):
    def test_receiver_records_contract_issues_without_blocking_data(self) -> None:
        monitor = DataQualityMonitor()
        receiver = RuntimeDataReceiver(cache=ShortTermMemory({DataKind.FLOW: 60}), writer=_MemoryWriter(), quality_monitor=monitor)
        receiver.receive_tcp({"ycsb_xsfx": "U"})
        self.assertEqual(len(receiver.recent(DataKind.FLOW)), 1)
        self.assertEqual(monitor.snapshot()["total_issues"], 1)
    def test_receiver_persists_classified_runtime_record(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            repository = LongTermMemory(root=root)
            writer = _MemoryWriter()
            receiver = RuntimeDataReceiver(
                cache=ShortTermMemory({DataKind.FLOW: 60}),
                writer=writer,
                repository=repository,
                lambdas_module=_Lambdas(),
            )

            receiver.receive_tcp({"ycsb_xsfx": "U", "jtll_ddbh": "1"})

            records = repository.get_runtime_history(DataKind.FLOW)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["kind"], "flow")
            self.assertEqual(records[0]["source"], "tcp")
            self.assertEqual(records[0]["payload"]["jtll_ddbh"], "1")
            self.assertEqual(records[0]["intersection_id"], "1300068")
            self.assertEqual(len(receiver.recent(DataKind.FLOW)), 1)
            self.assertEqual(len(writer.records), 1)

            query_service = MemoryQueryLayer(
                cache=receiver.cache,
                result_warehouse=ResultWarehouse(),
                config_service=ConfigService(),
                repository=repository,
            )
            self.assertEqual(
                query_service.get_runtime_history(DataKind.FLOW)[0]["kind"],
                "flow",
            )

    def test_history_query_filters_and_retention(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            repository = LongTermMemory(root=root, runtime_max_records_per_kind=2)
            repository.store_runtime_data(
                DataKind.FLOW,
                {"sequence": 1},
                intersection_id="1300068",
                received_at="2026-08-05T08:00:00+00:00",
            )
            repository.store_runtime_data(
                DataKind.FLOW,
                {"sequence": 2},
                intersection_id="1300068",
                received_at="2026-08-05T09:00:00+00:00",
            )
            repository.store_runtime_data(
                DataKind.FLOW,
                {"sequence": 3},
                intersection_id="1300106",
                received_at="2026-08-05T10:00:00+00:00",
            )

            records = repository.get_runtime_history(
                DataKind.FLOW,
                intersection_id="1300068",
                start_at="2026-08-05T08:30:00+00:00",
                end_at="2026-08-05T09:30:00+00:00",
            )
            self.assertEqual([record["payload"]["sequence"] for record in records], [2])
            self.assertEqual(
                [record["payload"]["sequence"] for record in repository.get_runtime_history(DataKind.FLOW)],
                [2, 3],
            )

    def test_runtime_record_normalizes_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            repository = LongTermMemory(root=root)
            record = repository.store_runtime_data(
                DataKind.FLOW,
                {"sequence": 1},
                received_at="2026-08-05T08:00:00",
            )
            self.assertEqual(record["received_at"], "2026-08-05T08:00:00+00:00")
            with self.assertRaises(ValueError):
                repository.store_runtime_data(
                    DataKind.FLOW,
                    {"sequence": 2},
                    received_at="not-a-timestamp",
                )


if __name__ == "__main__":
    unittest.main()
