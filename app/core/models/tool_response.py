"""Agent 工具响应契约。"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


@dataclass(frozen=True, slots=True)
class ToolResponse:
    """统一只读工具与 Agent 的成功、失败响应结构。"""

    status: Literal["ok", "error"]
    summary: str
    data: Any = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        summary: str,
        data: Any,
        meta: Mapping[str, Any] | None = None,
    ) -> "ToolResponse":
        """创建成功响应。"""
        return cls(status="ok", summary=summary, data=data, meta=dict(meta or {}))

    @classmethod
    def error(
        cls,
        summary: str,
        meta: Mapping[str, Any] | None = None,
    ) -> "ToolResponse":
        """创建失败响应，失败时不暴露数据内容。"""
        return cls(status="error", summary=summary, data=None, meta=dict(meta or {}))

    def with_meta(self, **extra: Any) -> "ToolResponse":
        """返回附加元数据后的新响应，不修改原对象。"""
        meta = dict(self.meta)
        meta.update(extra)
        return ToolResponse(self.status, self.summary, self.data, meta)

    def to_dict(self) -> dict[str, Any]:
        """转换为保持既有工具协议不变的普通字典。"""
        return {
            "status": self.status,
            "summary": self.summary,
            "data": copy.deepcopy(self.data),
            "meta": copy.deepcopy(dict(self.meta)),
        }
