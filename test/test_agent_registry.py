"""统一工具注册中心测试。"""

from __future__ import annotations

import unittest

from agent.registry import ToolRegistry


def _handler(*, value: int = 0) -> dict:
    return {"status": "ok", "value": value}


class ToolRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()
        self.registry.register(
            name="echo",
            description="回显测试工具",
            parameters={"properties": {"value": {"type": "integer"}}},
            handler=_handler,
            action="demo.echo",
        )

    def test_schemas_expose_registered_tools(self) -> None:
        schemas = self.registry.tool_schemas()
        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["name"], "echo")
        self.assertEqual(schemas[0]["description"], "回显测试工具")
        self.assertIn("properties", schemas[0]["parameters"])

    def test_invoke_calls_handler_with_arguments(self) -> None:
        result = self.registry.invoke("echo", {"value": 42})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["value"], 42)

    def test_invoke_unknown_tool_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.registry.invoke("not_exist")

    def test_actions_map_action_to_tool_name(self) -> None:
        self.assertEqual(self.registry.actions(), {"demo.echo": "echo"})

    def test_register_overrides_same_name(self) -> None:
        self.registry.register(
            name="echo",
            description="覆盖版本",
            parameters={},
            handler=lambda **_: {"status": "ok", "value": "new"},
        )
        self.assertEqual(len(self.registry), 1)
        result = self.registry.invoke("echo")
        self.assertEqual(result["value"], "new")

    def test_contains_and_len(self) -> None:
        self.assertIn("echo", self.registry)
        self.assertNotIn("missing", self.registry)
        self.assertEqual(len(self.registry), 1)

    def test_actions_exclude_tools_without_action(self) -> None:
        self.registry.register(
            name="no_action",
            description="无动作工具",
            parameters={},
            handler=lambda **_: {"status": "ok"},
        )
        self.assertEqual(self.registry.actions(), {"demo.echo": "echo"})


if __name__ == "__main__":
    unittest.main()
