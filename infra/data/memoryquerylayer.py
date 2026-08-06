"""短期记忆与长期记忆的统一查询层。"""

from .api import RuntimeDataQueryService


class MemoryQueryLayer(RuntimeDataQueryService):
    """为运行模块和 Agent 提供统一只读查询。"""

