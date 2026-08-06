"""短期记忆抽象，当前由内存滑动窗口实现。"""

from .runtime_cache import RuntimeDataCache


class ShortTermMemory(RuntimeDataCache):
    """保存近期运行数据的短期记忆。"""

