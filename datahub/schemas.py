"""Shared data schemas for the data foundation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    """Return an ISO timestamp for stored records."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class RuntimeRecord:
    """一条已分类的运行数据记录。"""

    kind: str
    payload: dict[str, Any]
    intersection_id: str | None = None
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
