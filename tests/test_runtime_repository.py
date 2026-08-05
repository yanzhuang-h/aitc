"""运行数据仓库的独立行为测试。"""

from __future__ import annotations

import tempfile
import unittest

from infra.data import (
    ConfigService,
    DataKind,
    DataRepository,
    ResultWarehouse,
    RuntimeDataCache,
    RuntimeDataQueryService,
    RuntimeDataReceiver,
)


class _MemoryWriter:
    def __init__(self) -> None:
        self.records: list[tuple[DataKind, dict]] = []

    def write(self, kind: DataKind, data: dict) -> None:
        self.records.append((kind, data))


class RuntimeRepositoryTest(unittest.TestCase):
    def test_receiver_persists_classified_runtime_record(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            repository = DataRepository(root=root)
            writer = _MemoryWriter()
            receiver = RuntimeDataReceiver(
                cache=RuntimeDataCache({DataKind.FLOW: 60}),
                writer=writer,
                repository=repository,
            )

            receiver.receive_tcp({"ycsb_xsfx": "U", "jtll_ddbh": "1"})

            records = repository.get_runtime_history(DataKind.FLOW)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["kind"], "flow")
            self.assertEqual(records[0]["source"], "tcp")
            self.assertEqual(records[0]["payload"]["jtll_ddbh"], "1")
            self.assertEqual(len(receiver.recent(DataKind.FLOW)), 1)
            self.assertEqual(len(writer.records), 1)

            query_service = RuntimeDataQueryService(
                cache=receiver.cache,
                result_warehouse=ResultWarehouse(),
                config_service=ConfigService(),
                repository=repository,
            )
            self.assertEqual(
                query_service.get_runtime_history(DataKind.FLOW)[0]["kind"],
                "flow",
            )


if __name__ == "__main__":
    unittest.main()
