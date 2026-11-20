"""Agent 意图注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.core.tool_registry import ToolRegistry as ToolRegistry, ToolSpec as ToolSpec


@dataclass(frozen=True, slots=True)
class IntentSpec:
    """单个意图的注册信息。"""

    name: str
    description: str
    handler: Callable[..., dict[str, Any]]


class IntentRegistry:
    """意图注册中心：显式意图的精确路由表。

    与 ``ToolRegistry`` 同风格：新增意图只需调用 ``register()``，
    无需再改 Harness 的分发逻辑。未匹配的意图由 Harness 负责
    交给自主判断 Agent 或兜底逻辑处理（本注册表不感知）。
    """

    def __init__(self) -> None:
        self._intents: dict[str, IntentSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: Callable[..., dict[str, Any]],
    ) -> None:
        """注册一个意图；同名注册会覆盖。"""
        self._intents[name] = IntentSpec(
            name=name,
            description=description,
            handler=handler,
        )

    def get(self, name: str) -> IntentSpec | None:
        """按名称取意图；未注册返回 None。"""
        return self._intents.get(name)

    def names(self) -> list[str]:
        """返回已注册意图名列表。"""
        return list(self._intents.keys())

    def describe(self) -> list[dict[str, str]]:
        """返回意图清单（名称 + 描述），供兜底提示与可观测性使用。"""
        return [
            {"name": spec.name, "description": spec.description}
            for spec in self._intents.values()
        ]

    def __contains__(self, name: str) -> bool:
        return name in self._intents

    def __len__(self) -> int:
        return len(self._intents)
