"""Agent 工具注册中心。

工具定义（schema）与处理函数（handler）在注册时一次性绑定，
Agent 层通过 ``tool_schemas()`` / ``invoke()`` 统一访问。
新增工具只需调用 ``register()``，无需再改分发逻辑。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """单个工具的注册信息。"""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., dict[str, Any]]
    action: str | None = None  # 符号路由动作名（可选）


class ToolRegistry:
    """工具注册中心：注册、查询 schema、统一调用。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: Mapping[str, Any],
        handler: Callable[..., dict[str, Any]],
        action: str | None = None,
    ) -> None:
        """注册一个工具；同名注册会覆盖。"""
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            parameters=dict(parameters),
            handler=handler,
            action=action,
        )

    def names(self) -> list[str]:
        """返回已注册工具名列表。"""
        return list(self._tools.keys())

    def all_specs(self) -> list[ToolSpec]:
        """返回全部已注册工具定义，供跨注册中心合并使用。"""
        return list(self._tools.values())

    def actions(self) -> dict[str, str]:
        """返回符号路由动作名到工具名的映射（仅含注册了 action 的工具）。"""
        return {spec.action: spec.name for spec in self._tools.values() if spec.action}

    def tool_schemas(self) -> list[dict[str, Any]]:
        """返回 OpenAI function calling 格式的工具定义列表。"""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": copy.deepcopy(spec.parameters),
            }
            for spec in self._tools.values()
        ]

    def invoke(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """按名称调用工具。未知工具抛 KeyError。"""
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"unknown tool: {name}")
        return spec.handler(**dict(arguments or {}))

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


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
