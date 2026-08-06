"""记忆查询层兼容入口，新代码请使用 ``infra.data.memory``。"""

from .memory.memoryquerylayer import MemoryQueryLayer

__all__ = ["MemoryQueryLayer"]
