"""Stable function interface around the existing DQN selector."""

from lib.DQN_Select import DQN_select

from .types import ControlResult, IntersectionControlRequest


def validate_control_plan(plan):
    """Validate and normalize the historical ten-element control plan.

    Args:
        plan: Sequence returned by the legacy selector. Indexes 0-7 are green
            times in seconds, index 8 is reserved, and index 9 is state number.

    Returns:
        tuple[list[int], list[str]]: Integer plan and non-fatal warnings.

    Raises:
        ValueError: If the plan is not a ten-element numeric sequence or has a
            negative phase time in indexes 0-7.
    """
    if not isinstance(plan, (list, tuple)) or len(plan) != 10:
        raise ValueError("control plan must contain exactly 10 elements")
    if any(not isinstance(value, (int, float)) for value in plan):
        raise ValueError("control plan elements must be numeric")
    normalized = [int(value) for value in plan]
    if any(value < 0 for value in normalized[:8]):
        raise ValueError("phase green times at indexes 0-7 cannot be negative")
    warnings = []
    if normalized == [0] * 10:
        warnings.append("selector returned an all-zero fallback plan")
    return normalized, warnings


def generate_intersection_plan(request: IntersectionControlRequest) -> ControlResult:
    """Generate one intersection plan using the unchanged DQN dispatch logic.

    Args:
        request: Structured intersection observations. ``cross_id`` must be a
            non-empty ID string; ``current_time`` is Unix seconds. All maps use
            the same raw formats currently passed by Server_AITC.

    Returns:
        ControlResult: A normalized ten-element plan plus the legacy coordinate,
        model and experience diagnostics. Algorithm/runtime failures are returned
        as ``success=false`` rather than raised, making this entry suitable for
        an external model tool caller.
    """
    cross_id = str(request.cross_id).strip()
    if not cross_id:
        return ControlResult(
            success=False, cross_id="", plan=[0] * 10, source="dqn",
            error="cross_id cannot be empty",
        )

    try:
        plan, coordinate_data, model_info, experience_info = DQN_select(
            request.traffic_vector,
            request.queue_vector,
            request.traffic_vector_duration2,
            request.current_time,
            request.flow_map,
            request.queue_map,
            request.stage_map,
            request.previous_coordinate,
            request.predicted_flow,
            request.predicted_queue,
            request.extend_map,
            request.overflow_map,
            request.radar_map,
            cross_id,
            request.boyan_map,
        )
        normalized_plan, warnings = validate_control_plan(plan)
        return ControlResult(
            success=True,
            cross_id=cross_id,
            plan=normalized_plan,
            source="dqn_selector",
            coordinate_data=coordinate_data or {},
            model_info=model_info or {},
            experience_info=experience_info or {},
            warnings=warnings,
        )
    except Exception as exc:
        return ControlResult(
            success=False, cross_id=cross_id, plan=[0] * 10,
            source="dqn_selector", error=f"{type(exc).__name__}: {exc}",
        )

