"""运行数据的通用校验函数。"""

from __future__ import annotations

from typing import Any


def is_millisecond_timestamp(value: Any) -> bool:
    """判断值是否可作为旧预测文件使用的毫秒时间戳。"""
    if value is None or isinstance(value, bool):
        return False
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True
