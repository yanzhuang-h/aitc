"""运行数据写入门面。

当前先包裹既有 `Write_to_file.py`，保持日志格式稳定，同时为数据底座
提供统一的输出边界。
"""

from __future__ import annotations

from typing import Any

from .classifier import DataKind
from .output_store import FileRuntimeOutputStore


class RuntimeDataWriter:
    """使用现有日志文件写入运行数据。"""

    def __init__(self, store: FileRuntimeOutputStore | None = None) -> None:
        self.store = store or FileRuntimeOutputStore()

    def start_filename_updater(self) -> None:
        self.store.start_filename_updater()

    def write(self, kind: DataKind, data: dict[str, Any]) -> None:
        self.store.write(self._resolve_category(kind), data)

    def write_flow_prediction(self, data: dict[str, Any] | str) -> None:
        self.store.write("flow_pre", data)

    def write_queue_prediction(self, data: dict[str, Any] | str) -> None:
        self.store.write("queue_pre", data)

    def write_send_result(self, data: dict[str, Any]) -> None:
        self.store.write("send", data)

    def write_phase_check(self, data: dict[str, Any] | str) -> None:
        self.store.write("phase_check", data, timestamp_line=True)

    def write_experience(self, exp_list: dict[str, Any], intersection_id: str) -> None:
        self.store.write_experience(exp_list, intersection_id)

    def _resolve_category(self, kind: DataKind) -> str:
        mapping = {
            DataKind.FLOW: "flow", DataKind.QUEUE: "queue", DataKind.STAGE: "stage",
            DataKind.HEARTBEAT: "heartbeat", DataKind.ONLINE: "online", DataKind.LATEST: "online",
            DataKind.EXTEND: "extend", DataKind.OVERFLOW_WARNING: "overflowWarning",
            DataKind.RADAR: "radar", DataKind.RADAR_EVENT: "radar", DataKind.BOYAN: "boyan",
            DataKind.HISTORY: "history",
        }
        return mapping.get(kind, "history")
