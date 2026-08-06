"""数据底座的历史兼容 API。

新的业务代码应直接使用 ``LongTermMemory``、``ShortTermMemory`` 和
``MemoryQueryLayer``。这里保留旧名称，方便协作分支平滑迁移。
"""

from functools import lru_cache

from .memory.longtermmemory import LongTermMemory
from .memory.memoryquerylayer import MemoryQueryLayer


# 旧名称保留为别名，避免产生两套不一致的仓库实现。
DataRepository = LongTermMemory
RuntimeDataQueryService = MemoryQueryLayer


@lru_cache(maxsize=1)
def get_default_repository() -> LongTermMemory:
    """返回默认长期记忆实例。"""
    return LongTermMemory()


__all__ = [
    "DataRepository",
    "LongTermMemory",
    "MemoryQueryLayer",
    "RuntimeDataQueryService",
    "get_default_repository",
]
