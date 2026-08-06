"""运行窗口数据的聚合入口。"""

from __future__ import annotations

from typing import Any

from . import cache_processor
from .classifier import DataKind
from .memory.shorttermmemory import ShortTermMemory


class RuntimeDataProcessor:
    """将运行窗口转换为既有决策算法需要的数据结构。"""

    def __init__(self, cache: ShortTermMemory, lambdas_module: Any) -> None:
        self.cache = cache
        self.lambdas = lambdas_module

    def flow(self):
        return cache_processor.process_flow_data(
            self.cache.recent_data(DataKind.FLOW), self.lambdas
        )

    def flow_duration(self, duration_seconds: int):
        return cache_processor.process_flow_data(
            self.cache.duration_data(DataKind.FLOW, duration_seconds), self.lambdas
        )

    def queue(self):
        return cache_processor.process_queue_data(
            self.cache.recent_data(DataKind.QUEUE), self.lambdas
        )

    def stage(self):
        return cache_processor.process_stage_data(
            self.cache.recent_data(DataKind.STAGE), self.lambdas
        )

    def extend(self):
        return cache_processor.process_extend_data(
            self.cache.recent_legacy_tuples(DataKind.EXTEND), self.lambdas
        )

    def online(self):
        return cache_processor.process_online_data(
            self.cache.recent_legacy_tuples(DataKind.ONLINE), self.lambdas
        )

    def radar(self):
        return cache_processor.process_radar_data(
            self.cache.recent_legacy_tuples(DataKind.RADAR), self.lambdas
        )

    def radar_event(self, event_map, overflow_warning_map):
        return cache_processor.process_radar_event_data(
            event_map,
            overflow_warning_map,
            self.lambdas,
        )

    def boyan(self):
        return cache_processor.process_boyan_data(
            self.cache.recent_legacy_tuples(DataKind.BOYAN), self.lambdas
        )

    def snapshot(self) -> dict[str, Any]:
        """按当前决策管线期望的形态返回运行窗口快照。"""
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
