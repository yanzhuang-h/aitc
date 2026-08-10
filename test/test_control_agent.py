"""分步放行控制流程 Agent 的测试（使用假 LLM 客户端）。"""

import logging
import unittest

from agent.control_agent import ControlProcessAgent


class FakeLLMClient:
    """模拟 OpenAI 兼容客户端，可配置成功或失败。"""

    def __init__(self, content: str = "思考中...", fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.calls = 0
        self.model = "fake-model"

    def chat(self, messages, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("mock failure")
        return type("Result", (), {"content": self.content})()


def _quiet_logger() -> logging.Logger:
    logger = logging.getLogger("test.control_agent")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


class ControlProcessAgentTest(unittest.TestCase):
    def test_run_returns_ten_steps_with_thoughts(self):
        client = FakeLLMClient(content="我正在分析车流压力...")
        agent = ControlProcessAgent(client, logger=_quiet_logger())
        result = agent.run({"cross_id": "1300068", "request_text": "生成方案"})
        self.assertEqual(result["status"], "ok")
        steps = result["data"]["steps"]
        self.assertEqual(len(steps), 10)
        for step in steps:
            self.assertIn("title", step)
            self.assertEqual(step["llm_thought"], "我正在分析车流压力...")
            self.assertIn("data", step)
        self.assertEqual(client.calls, 10)
        self.assertEqual(result["meta"]["llm_model"], "fake-model")
        self.assertEqual(result["meta"]["step_count"], 10)

    def test_run_falls_back_when_llm_fails(self):
        client = FakeLLMClient(fail=True)
        agent = ControlProcessAgent(client, logger=_quiet_logger())
        result = agent.run({"cross_id": "1300068"})
        steps = result["data"]["steps"]
        self.assertEqual(len(steps), 10)
        # 每步失败后重试一次，共 2 次调用
        self.assertEqual(client.calls, 20)
        for step in steps:
            self.assertTrue(step["llm_thought"])

    def test_run_requires_cross_id(self):
        agent = ControlProcessAgent(FakeLLMClient(), logger=_quiet_logger())
        result = agent.run({"cross_id": "  "})
        self.assertEqual(result["status"], "error")
        self.assertEqual(agent.llm_client.calls, 0)

    def test_run_uses_data_hub_when_available(self):
        class FakeQuery:
            def get_runtime_data(self, kind, limit=None):
                if kind == "flow":
                    return [{"intersection_id": "1300068", "payload": {"count": 6}}]
                return []

        client = FakeLLMClient()
        agent = ControlProcessAgent(client, query_service=FakeQuery(), logger=_quiet_logger())
        result = agent.run({"cross_id": "1300068"})
        self.assertEqual(result["data"]["data_source"], "data_hub")
        first = result["data"]["steps"][0]["data"]
        self.assertIn("data_hub", first)


if __name__ == "__main__":
    unittest.main()
