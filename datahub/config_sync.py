"""数据底座配置同步生命周期管理。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lib.nacos_floating_value import (
    NacosFloatingValueSync,
    NacosIntersectionResultConfigSync,
    NacosRoadStateSync,
    NacosTimeScheduleSync,
)


class ConfigSyncManager:
    """统一管理配置同步任务的创建、启动和停止。"""

    def __init__(self, tasks: Mapping[str, Any] | None = None) -> None:
        self.tasks = dict(tasks) if tasks is not None else {
            "floating_value": NacosFloatingValueSync(),
            "intersection_result": NacosIntersectionResultConfigSync(),
            "road_state": NacosRoadStateSync(),
            "time_schedule": NacosTimeScheduleSync(),
        }

    def start(self) -> dict[str, Any]:
        """启动全部配置同步任务，并返回各任务的启动结果。"""
        return {name: task.start() for name, task in self.tasks.items()}

    def stop(self) -> None:
        """停止全部配置同步任务。"""
        for task in self.tasks.values():
            task.stop()
