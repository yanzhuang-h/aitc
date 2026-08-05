"""旧缓存处理函数适配层。

算法仍保留在现有模块中。本文件只集中调用入口，让服务端后续依赖
`infra.data`，而不是直接导入各个处理函数。
"""

from __future__ import annotations

from typing import Any

from .classifier import DataKind
from .runtime_cache import RuntimeDataCache


class LegacyCacheProcessor:
    """使用当前 `Process_cache_data.py` 函数处理运行窗口。"""

    def __init__(self, cache: RuntimeDataCache) -> None:
        self.cache = cache

    def flow(self):
        import Process_cache_data
        return Process_cache_data.process_flow_data(
            self.cache.recent_data(DataKind.FLOW)
        )

    def flow_duration(self, duration_seconds: int):
        import Process_cache_data
        return Process_cache_data.process_flow_data(
            self.cache.duration_data(DataKind.FLOW, duration_seconds)
        )

    def queue(self):
        import Process_cache_data
        return Process_cache_data.process_queue_data(
            self.cache.recent_data(DataKind.QUEUE)
        )

    def stage(self):
        import Process_cache_data
        return Process_cache_data.process_stage_data(
            self.cache.recent_data(DataKind.STAGE)
        )

    def extend(self):
        import Process_cache_data
        return Process_cache_data.process_extend_data(
            self.cache.recent_legacy_tuples(DataKind.EXTEND)
        )

    def online(self):
        import Process_cache_data
        return Process_cache_data.process_online_data(
            self.cache.recent_legacy_tuples(DataKind.ONLINE)
        )

    def radar(self):
        import Process_cache_data
        return Process_cache_data.process_radar_data(
            self.cache.recent_legacy_tuples(DataKind.RADAR)
        )

    def boyan(self):
        import Process_cache_data
        return Process_cache_data.process_boyan_data(
            self.cache.recent_legacy_tuples(DataKind.BOYAN)
        )

    def snapshot(self) -> dict[str, Any]:
        """按旧代码期望的数据形态返回当前窗口快照。"""
        return {
            "flow": self.cache.recent_data(DataKind.FLOW),
            "queue": self.cache.recent_data(DataKind.QUEUE),
            "stage": self.cache.recent_data(DataKind.STAGE),
            "extend": self.cache.recent_legacy_tuples(DataKind.EXTEND),
            "online": self.cache.recent_legacy_tuples(DataKind.ONLINE),
            "latest": self.cache.recent_legacy_tuples(DataKind.LATEST),
            "radar": self.cache.recent_legacy_tuples(DataKind.RADAR),
            "boyan": self.cache.recent_legacy_tuples(DataKind.BOYAN),
        }
