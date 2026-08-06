"""长期记忆抽象，当前由本地文件仓库实现。"""

from .api import DataRepository


class LongTermMemory(DataRepository):
    """保存可追溯历史、配置和经验数据的长期记忆。"""

