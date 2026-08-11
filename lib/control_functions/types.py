"""Typed request and result objects for callable traffic-control functions."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class IntersectionControlRequest:
    """All observations needed to calculate one intersection plan.

    ``cross_id`` is the string intersection ID and ``current_time`` is a Unix
    timestamp in seconds. Vector fields retain the existing DQN feature order.
    Map fields retain the Server_AITC runtime dictionaries; their keys are
    normally observation timestamps and their values are sensor records.
    Empty dictionaries/lists mean that the corresponding source has no data.
    """

    cross_id: str
    current_time: float
    traffic_vector: list[Any] = field(default_factory=list)
    queue_vector: list[Any] = field(default_factory=list)
    traffic_vector_duration2: list[Any] = field(default_factory=list)
    flow_map: dict[Any, Any] = field(default_factory=dict)
    queue_map: dict[Any, Any] = field(default_factory=dict)
    stage_map: dict[Any, Any] = field(default_factory=dict)
    previous_coordinate: dict[str, Any] = field(default_factory=dict)
    predicted_flow: dict[Any, Any] = field(default_factory=dict)
    predicted_queue: dict[Any, Any] = field(default_factory=dict)
    extend_map: dict[Any, Any] = field(default_factory=dict)
    overflow_map: dict[Any, Any] = field(default_factory=dict)
    radar_map: dict[Any, Any] = field(default_factory=dict)
    boyan_map: dict[Any, Any] = field(default_factory=dict)


@dataclass
class ControlResult:
    """Normalized result returned by a single-intersection control function.

    ``plan`` contains ten integers. Indexes 0-7 are phase green times in
    seconds, index 8 is reserved, and index 9 is the plan/state number.
    ``source`` identifies the function that produced the result. Diagnostic
    dictionaries preserve the existing DQN coordinate/model/experience output.
    """

    success: bool
    cross_id: str
    plan: list[int]
    source: str
    coordinate_data: dict[str, Any] = field(default_factory=dict)
    model_info: dict[str, Any] = field(default_factory=dict)
    experience_info: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary for APIs or model tools."""
        return asdict(self)

