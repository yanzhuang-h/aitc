"""周期决策结果的内部模型。"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """封装单路口控制结果，并保持下游 TCP 协议字典兼容。"""

    intersection_id: str
    payload: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "DecisionResult":
        """从既有控制报文创建模型并提取路口编号。"""
        copied_payload = copy.deepcopy(dict(payload))
        try:
            intersection_id = str(copied_payload["additional"]["tlLogic"]["id"])
        except (KeyError, TypeError) as error:
            raise ValueError("decision payload must include additional.tlLogic.id") from error
        return cls(intersection_id=intersection_id, payload=copied_payload)

    def to_payload(self) -> dict[str, Any]:
        """输出既有控制报文字典，供结果仓库和 TCP 发送器使用。"""
        return copy.deepcopy(dict(self.payload))
