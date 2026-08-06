import tempfile
import unittest

from infra.data import ConfigService, LongTermMemory, MemoryQueryLayer, ResultWarehouse, ShortTermMemory
from infra.data.classifier import DataKind


class MemoryLayersTest(unittest.TestCase):
    def test_memory_entrypoints_preserve_existing_behavior(self):
        with tempfile.TemporaryDirectory() as root:
            short_term = ShortTermMemory({DataKind.FLOW: 60})
            long_term = LongTermMemory(root=root)
            short_term.add(DataKind.FLOW, {"value": 1})
            long_term.store_runtime_data(DataKind.FLOW, {"value": 1})
            query = MemoryQueryLayer(short_term, ResultWarehouse(), ConfigService(), long_term)

            self.assertEqual(query.get_runtime_size(DataKind.FLOW), 1)
            self.assertEqual(query.get_runtime_history(DataKind.FLOW)[0]["payload"]["value"], 1)


if __name__ == "__main__":
    unittest.main()
