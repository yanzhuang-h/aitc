"""核心模型与既有协议的兼容性测试。"""

from __future__ import annotations

import unittest

from app.core.models import DecisionResult, ToolResponse
from infra.data import ResultWarehouse


class CoreModelsTest(unittest.TestCase):
    def test_tool_response_keeps_existing_dict_contract(self) -> None:
        response = ToolResponse.ok("查询成功", {"count": 1}, {"source": "test"})

        self.assertEqual(
            response.to_dict(),
            {
                "status": "ok",
                "summary": "查询成功",
                "data": {"count": 1},
                "meta": {"source": "test"},
            },
        )

    def test_decision_result_and_warehouse_keep_payload_shape(self) -> None:
        payload = {"additional": {"tlLogic": {"id": "1300068"}}, "modelInfo": {}}
        model = DecisionResult.from_payload(payload)
        warehouse = ResultWarehouse()
        warehouse.replace([model])

        snapshot = warehouse.snapshot()
        self.assertEqual(model.intersection_id, "1300068")
        self.assertEqual(snapshot, [payload])
        snapshot[0]["modelInfo"]["changed"] = True
        self.assertNotIn("changed", warehouse.snapshot()[0]["modelInfo"])

    def test_decision_result_rejects_payload_without_intersection(self) -> None:
        with self.assertRaises(ValueError):
            DecisionResult.from_payload({"additional": {}})


if __name__ == "__main__":
    unittest.main()
