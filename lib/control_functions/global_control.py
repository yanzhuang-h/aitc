"""Documented callable interfaces for the three global road categories."""

from lib.Global_intersection_coordinate import (
    coordinate_flow_roads,
    coordinate_internet_roads,
    coordinate_mixed_roads,
    coordinate_without_green_wave,
    intern_road_id,
    shipin1_road,
    shipin_road,
)


ROAD_TYPE_INTERNET = "internet"
ROAD_TYPE_MIXED = "mixed"
ROAD_TYPE_FLOW = "flow"


def get_intersection_processing_types(cross_id):
    """Return every configured global processor for an intersection ID.

    Returns a tuple in legacy execution order: ``internet`` for membership in
    ``intern_road_id``, ``mixed`` for ``shipin_road``, and ``flow`` for
    ``shipin1_road``. Some existing IDs belong to two sets and therefore return
    two values; preserving both is necessary to keep the current behavior.
    Invalid or unregistered IDs return an empty tuple.
    """
    try:
        numeric_id = int(str(cross_id))
    except (TypeError, ValueError):
        return ()
    processor_types = []
    if numeric_id in intern_road_id:
        processor_types.append(ROAD_TYPE_INTERNET)
    if numeric_id in shipin_road:
        processor_types.append(ROAD_TYPE_MIXED)
    if numeric_id in shipin1_road:
        processor_types.append(ROAD_TYPE_FLOW)
    return tuple(processor_types)


def process_internet_intersections(plans, coordinate_data, online_data,
                                   overflow_data, extend_data=None):
    """Run the pure-internet processor and all shared final adjustments.

    ``plans`` maps string intersection IDs to ten-element plans. ``online_data``
    contains Internet road observations; ``coordinate_data`` contains phase
    starts; ``overflow_data`` and optional ``extend_data`` retain their existing
    runtime formats. The returned mapping has the same plan format. Green wave
    is excluded; forced state, time additions and floating values are retained.
    """
    return coordinate_internet_roads(
        plans, coordinate_data, online_data, overflow_data, extend_data
    )


def process_mixed_intersections(plans, coordinate_data, online_data,
                                overflow_data, extend_data=None):
    """Run the Internet-plus-flow ``shipin_road`` processor.

    Input/output formats and shared post-processing are identical to
    :func:`process_internet_intersections`; green-wave processing is excluded.
    """
    return coordinate_mixed_roads(
        plans, coordinate_data, online_data, overflow_data, extend_data
    )


def process_flow_intersections(plans, coordinate_data, online_data,
                               overflow_data, extend_data=None):
    """Run the pure-flow ``shipin1_road`` processor.

    Input/output formats and shared post-processing are identical to
    :func:`process_internet_intersections`; green-wave processing is excluded.
    """
    return coordinate_flow_roads(
        plans, coordinate_data, online_data, overflow_data, extend_data
    )


def process_all_intersections(plans, coordinate_data, online_data,
                              overflow_data, extend_data=None):
    """Run all three processors in legacy order without green-wave processing."""
    return coordinate_without_green_wave(
        plans, coordinate_data, online_data, overflow_data, extend_data
    )
