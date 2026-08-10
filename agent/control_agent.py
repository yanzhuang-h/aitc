"""单路口放行控制的分步流程 Agent。

流程骨架是确定性的（见 ``app/core/tools/control_flow.py`` 的规则函数），
本层负责逐步执行，并让大模型为每一步生成可展示的"思考过程"。
即使大模型偶发失败，流程也会回退为规则结果，不中断。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Mapping

from app.core.models import ToolResponse
from app.core.tools.control_flow import CONTROL_STEPS, build_initial_context, query_data_hub_summary
from app.infrastructure.llm import OpenAICompatibleLLMClient


class ControlProcessAgent:
    """分步放行控制：规则函数判断 + 大模型逐步思考展示。"""

    def __init__(
        self,
        llm_client: OpenAICompatibleLLMClient,
        query_service: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.query_service = query_service
        self.logger = logger or logging.getLogger("aitc.control_process")

    def run(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """执行完整分步流程，返回每步的思考与结构化结果。"""
        cross_id = request.get("cross_id")
        request_text = request.get("request_text")
        if not isinstance(cross_id, str) or not cross_id.strip():
            return ToolResponse.error("cross_id must be a non-empty string").to_dict()
        cross_id = cross_id.strip()

        context = build_initial_context(cross_id)
        data_hub = query_data_hub_summary(cross_id, self.query_service)
        if data_hub:
            context["data_hub"] = data_hub
        if isinstance(request_text, str) and request_text.strip():
            context["request_text"] = request_text.strip()

        steps = []
        for index, item in enumerate(CONTROL_STEPS, start=1):
            data = item["fn"](context)
            thought = self._explain(item["title"], data)
            steps.append({
                "step": index,
                "key": item["key"],
                "title": item["title"],
                "llm_thought": thought,
                "data": data,
            })

        summary = steps[-1]["llm_thought"] if steps else "流程执行完成。"
        return ToolResponse.ok(
            summary=summary,
            data={
                "cross_id": cross_id,
                "data_source": "data_hub" if data_hub else "default_simulation",
                "steps": steps,
            },
            meta={
                "llm_model": getattr(self.llm_client, "model", None),
                "step_count": len(steps),
            },
        ).to_dict()

    def _explain(self, title: str, data: Mapping[str, Any]) -> str:
        """让大模型根据规则结果生成该步的思考说明。"""
        messages = [
            {
                "role": "system",
                "content": (
                    "你是交通信号控制 Agent。请用第一人称、口语化、简洁地说明你"
                    "在当前步骤的思考与判断依据。只输出中文说明，不要输出 JSON。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"当前步骤：{title}\n"
                    f"规则引擎结果：{self._compact(data)}\n"
                    "请描述你这一步的思考过程。"
                ),
            },
        ]
        for attempt in (1, 2):
            try:
                result = self.llm_client.chat(
                    messages, temperature=0.4, top_p=0.9, max_tokens=200
                )
                if result.content.strip():
                    return result.content.strip()
            except Exception as error:
                self.logger.warning("生成步骤思考失败(第%d次): %s", attempt, error)
                if attempt == 1:
                    time.sleep(0.5)
        return f"规则引擎已完成「{title}」步骤，判断结果见下方数据。"

    @staticmethod
    def _compact(data: Mapping[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False)
