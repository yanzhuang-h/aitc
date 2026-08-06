"""短期记忆兼容入口，新代码请使用 ``infra.data.memory``。"""

from .memory.shorttermmemory import DEFAULT_WINDOW_SECONDS, ShortTermMemory, WindowItem

__all__ = ["DEFAULT_WINDOW_SECONDS", "ShortTermMemory", "WindowItem"]
