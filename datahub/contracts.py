"""运行数据契约及非阻断式校验。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .classifier import DataKind, DataSource


@dataclass(frozen=True, slots=True)
class DataContract:
    """单类运行数据的最小字段契约。"""

    kind: DataKind
    sources: tuple[DataSource, ...]
    required_fields: tuple[str, ...]
    timestamp_fields: tuple[str, ...] = ()
    intersection_fields: tuple[str, ...] = ()


CONTRACTS: dict[DataKind, DataContract] = {
    DataKind.FLOW: DataContract(DataKind.FLOW, (DataSource.TCP,), ("ycsb_xsfx", "jtll_ddbh", "ycsb_cdbh", "ts"), ("ts",), ("CrossId", "intersection_id", "jtll_ddbh")),
    DataKind.QUEUE: DataContract(DataKind.QUEUE, (DataSource.TCP,), ("jtll_ddbh", "start_time", "car_nums"), ("start_time",), ("CrossId", "intersection_id", "jtll_ddbh")),
    DataKind.STAGE: DataContract(DataKind.STAGE, (DataSource.TCP,), ("CrossId", "time", "curStageNo", "curStageLen"), ("time",), ("CrossId",)),
    DataKind.HEARTBEAT: DataContract(DataKind.HEARTBEAT, (DataSource.TCP,), ("heartbeat",)),
    DataKind.ONLINE: DataContract(DataKind.ONLINE, (DataSource.TCP,), ("rid",)),
    DataKind.LATEST: DataContract(DataKind.LATEST, (DataSource.TCP,), ("inter_id",)),
    DataKind.EXTEND: DataContract(DataKind.EXTEND, (DataSource.TCP,), ("CrossId", "curStageRemainLen"), (), ("CrossId",)),
    DataKind.OVERFLOW_WARNING: DataContract(DataKind.OVERFLOW_WARNING, (DataSource.TCP,), ("distance", "jtll_ddbh", "ts"), ("ts",), ("jtll_ddbh",)),
    DataKind.RADAR: DataContract(DataKind.RADAR, (DataSource.HTTP,), ("deviceNo",)),
    DataKind.RADAR_EVENT: DataContract(DataKind.RADAR_EVENT, (DataSource.HTTP,), ("deviceNo", "eventType")),
    DataKind.BOYAN: DataContract(DataKind.BOYAN, (DataSource.HTTP,), ("deviceId",)),
}


def validate_contract(kind: DataKind, payload: Mapping[str, Any], source: DataSource) -> list[str]:
    """返回契约问题列表；调用方可记录告警而不影响旧链路。"""
    contract = CONTRACTS.get(kind)
    if contract is None:
        return []
    issues = []
    if source not in contract.sources:
        issues.append(f"来源不符合契约: {source.value}")
    for field in contract.required_fields:
        if payload.get(field) is None:
            issues.append(f"缺少字段: {field}")
    for field in contract.timestamp_fields:
        value = payload.get(field)
        if value is not None:
            try:
                int(value)
            except (TypeError, ValueError):
                issues.append(f"时间字段不是整数时间戳: {field}")
    return issues
