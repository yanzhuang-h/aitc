"""运行数据分类规则。

第一阶段保持旧系统基于字段判断数据类型的规则不变，只把规则从
`Server_AITC.py` 中抽出来，便于后续继续瘦身入口文件。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class DataKind(str, Enum):
    FLOW = "flow"
    QUEUE = "queue"
    STAGE = "stage"
    HEARTBEAT = "heartbeat"
    ONLINE = "online"
    LATEST = "latest"
    EXTEND = "extend"
    OVERFLOW_WARNING = "overflow_warning"
    RADAR = "radar"
    RADAR_EVENT = "radar_event"
    BOYAN = "boyan"
    HISTORY = "history"
    UNSUPPORTED = "unsupported"


class DataSource(str, Enum):
    TCP = "tcp"
    HTTP = "http"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ClassifiedData:
    kind: DataKind
    item: dict[str, Any]
    source: DataSource = DataSource.UNKNOWN
    reason: str = ""


def classify_data(
    item: Mapping[str, Any],
    source: DataSource | str = DataSource.UNKNOWN,
) -> ClassifiedData:
    """使用旧系统字段规则识别单条运行数据。"""
    if isinstance(source, DataSource):
        source_value = source
    else:
        try:
            source_value = DataSource(source)
        except ValueError:
            source_value = DataSource.UNKNOWN
    data = dict(item)

    if source_value == DataSource.HTTP:
        if "deviceNo" in data:
            if data.get("eventType") is None:
                return ClassifiedData(DataKind.RADAR, data, source_value, "deviceNo")
            return ClassifiedData(DataKind.RADAR_EVENT, data, source_value, "deviceNo+eventType")
        if "deviceId" in data:
            return ClassifiedData(DataKind.BOYAN, data, source_value, "deviceId")
        return ClassifiedData(DataKind.HISTORY, data, source_value, "unknown http payload")

    if "ycsb_xsfx" in data:
        return ClassifiedData(DataKind.FLOW, data, source_value, "ycsb_xsfx")
    if "car_nums" in data:
        return ClassifiedData(DataKind.QUEUE, data, source_value, "car_nums")
    if "curStageLen" in data:
        return ClassifiedData(DataKind.STAGE, data, source_value, "curStageLen")
    if "heartbeat" in data:
        return ClassifiedData(DataKind.HEARTBEAT, data, source_value, "heartbeat")
    if "rid" in data:
        return ClassifiedData(DataKind.ONLINE, data, source_value, "rid")
    if "inter_id" in data:
        return ClassifiedData(DataKind.LATEST, data, source_value, "inter_id")
    if "curStageRemainLen" in data:
        return ClassifiedData(DataKind.EXTEND, data, source_value, "curStageRemainLen")
    if {"distance", "jtll_ddbh", "ts"}.issubset(data):
        return ClassifiedData(
            DataKind.OVERFLOW_WARNING,
            data,
            source_value,
            "distance+jtll_ddbh+ts",
        )

    return ClassifiedData(DataKind.HISTORY, data, source_value, "no known marker")
