"""Shared data schemas for the data foundation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def utc_now_iso() -> str:
    """Return an ISO timestamp for stored records."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TrafficRecord:
    """One traffic sensing record from a platform or local producer."""

    intersection_id: str
    payload: dict[str, Any]
    source: str = "unknown"
    timestamp: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TrafficRecord":
        return cls(
            intersection_id=str(data["intersection_id"]),
            payload=dict(data.get("payload", {})),
            source=str(data.get("source", "unknown")),
            timestamp=str(data.get("timestamp") or utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RuntimeRecord:
    """一条已分类的运行数据记录。"""

    kind: str
    payload: dict[str, Any]
    source: str = "unknown"
    received_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConfigItem:
    """A persisted configuration value."""

    key: str
    value: Any
    namespace: str = "default"
    updated_at: str = field(default_factory=utc_now_iso)

    def storage_key(self) -> str:
        return f"{self.namespace}:{self.key}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExperienceItem:
    """One experience-pool item used by algorithms or agents."""

    key: str
    value: dict[str, Any]
    category: str = "default"
    updated_at: str = field(default_factory=utc_now_iso)

    def storage_key(self) -> str:
        return f"{self.category}:{self.key}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
