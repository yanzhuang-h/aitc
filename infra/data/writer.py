"""运行数据写入门面。"""

from __future__ import annotations

from typing import Any

from .classifier import DataKind
from .output_store import FileRuntimeOutputStore


class RuntimeDataWriter:
    """通过本地输出仓库写入运行数据。"""

    def __init__(self, store: FileRuntimeOutputStore | None = None) -> None:
        self.store = store or FileRuntimeOutputStore()

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
