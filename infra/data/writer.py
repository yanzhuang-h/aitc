"""运行数据写入门面。

当前先包裹既有 `Write_to_file.py`，保持日志格式稳定，同时为数据底座
提供统一的输出边界。
"""

from __future__ import annotations

import json
from typing import Any

from .classifier import DataKind


class RuntimeDataWriter:
    """使用现有日志文件写入运行数据。"""

    def __init__(self, legacy_writer: Any | None = None) -> None:
        if legacy_writer is None:
            import Write_to_file as legacy_writer
        self.legacy_writer = legacy_writer
        if hasattr(self.legacy_writer, "update_file_name"):
            self.legacy_writer.update_file_name()

    def start_filename_updater(self) -> None:
        if hasattr(self.legacy_writer, "start_filename_updater"):
            self.legacy_writer.start_filename_updater()

    def write(self, kind: DataKind, data: dict[str, Any]) -> None:
        text = json.dumps(data, ensure_ascii=False)
        writer = self._resolve_writer(kind)
        writer(text)

    def write_flow_prediction(self, data: dict[str, Any] | str) -> None:
        self.legacy_writer.write_to_flow_predict_file(data)

    def write_queue_prediction(self, data: dict[str, Any] | str) -> None:
        self.legacy_writer.write_to_queue_predict_file(data)

    def write_send_result(self, data: dict[str, Any]) -> None:
        self.legacy_writer.write_to_send_file(data)

    def write_phase_check(self, data: dict[str, Any] | str) -> None:
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        self.legacy_writer.write_to_phase_check_file(text)

    def write_experience(self, exp_list: dict[str, Any], intersection_id: str) -> None:
        self.legacy_writer.gen_EXP_Json(exp_list, intersection_id)

    def _resolve_writer(self, kind: DataKind):
        mapping = {
            DataKind.FLOW: self.legacy_writer.write_to_traffic_file,
            DataKind.QUEUE: self.legacy_writer.write_to_queue_file,
            DataKind.STAGE: self.legacy_writer.write_to_stage_file,
            DataKind.HEARTBEAT: self.legacy_writer.write_to_heartbeat_file,
            DataKind.ONLINE: self.legacy_writer.write_to_online_file,
            DataKind.LATEST: self.legacy_writer.write_to_online_file,
            DataKind.EXTEND: self.legacy_writer.write_to_extend_file,
            DataKind.OVERFLOW_WARNING: self.legacy_writer.write_to_overflowWarning_file,
            DataKind.RADAR: self.legacy_writer.write_to_radar_file,
            DataKind.RADAR_EVENT: self.legacy_writer.write_to_radar_file,
            DataKind.BOYAN: self.legacy_writer.write_to_boyan_file,
            DataKind.HISTORY: self.legacy_writer.write_to_history_file,
        }
        return mapping.get(kind, self.legacy_writer.write_to_history_file)
