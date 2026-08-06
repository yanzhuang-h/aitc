"""短期记忆的历史兼容入口。

新代码请使用 :class:`infra.data.shorttermmemory.ShortTermMemory`。
"""

from .shorttermmemory import DEFAULT_WINDOW_SECONDS, ShortTermMemory, WindowItem


# 保留旧类名，避免协作方和旧算法在迁移期间中断。
RuntimeDataCache = ShortTermMemory

__all__ = ["DEFAULT_WINDOW_SECONDS", "RuntimeDataCache", "ShortTermMemory", "WindowItem"]
