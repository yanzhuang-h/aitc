"""Receiver helpers for data producers.

This module keeps input normalization separate from repository persistence so
future platform, socket, or HTTP receivers can share the same write path.
"""

from __future__ import annotations

from typing import Any, Mapping

from .api import DataRepository, get_default_repository


class TrafficReceiver:
    """Receive traffic data from external producers."""

    def __init__(self, repository: DataRepository | None = None) -> None:
        self.repository = repository or get_default_repository()

    def receive(
        self,
        intersection_id: str,
        payload: Mapping[str, Any],
        source: str = "unknown",
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "intersection_id": intersection_id,
            "payload": dict(payload),
            "source": source,
        }
        if timestamp is not None:
            record["timestamp"] = timestamp
        return self.repository.receive_traffic(record)
