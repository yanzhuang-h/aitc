"""Versioned, validated release and rollback for runtime experience tables."""

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import tempfile

try:
    from lib.data_ANS.lane_policy import (
        configured_movement_lane_policy,
        policy_metadata,
    )
except ModuleNotFoundError:  # Supports direct execution from this directory.
    from lane_policy import configured_movement_lane_policy, policy_metadata


LANE_COUNT = 10
VALID_DIRECTIONS = {"U", "D", "L", "R", "UTL", "DTL", "LTL", "RTL"}
MIN_GREEN_TIME = 1
MAX_GREEN_TIME = 150


class ExperienceReleaseError(ValueError):
    pass


def _load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return copy.deepcopy(default)


def _write_json_atomic(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            delete=False,
        ) as file:
            temp_path = file.name
            json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _canonical_hash(data):
    content = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _normalize_vector(vector):
    if not isinstance(vector, list) or len(vector) != LANE_COUNT:
        raise ValueError("flow vector must contain exactly 10 lanes")
    normalized = []
    for value in vector:
        if isinstance(value, bool):
            raise ValueError("flow values must be integers")
        number = int(value)
        if number < 0 or number != value:
            raise ValueError("flow values must be non-negative integers")
        normalized.append(number)
    return normalized


def _configured_lane_sets(cross_config, direction):
    base_direction = direction[0]
    base_lanes = configured_movement_lane_policy(
        cross_config,
        base_direction,
        LANE_COUNT,
    )["eligible"]
    left_lanes = configured_movement_lane_policy(
        cross_config,
        base_direction + "TL",
        LANE_COUNT,
    )["eligible"]
    return base_lanes, left_lanes


def validate_experience_table(
    table,
    cross_info=None,
    required_road_ids=None,
    allow_legacy_records=False,
):
    """Validate a completed candidate before it can become a runtime table."""
    errors = []
    warnings = []
    summary = {
        "roads": 0,
        "directions": 0,
        "points": 0,
        "nonzero_lane_values": 0,
    }

    if not isinstance(table, dict) or not table:
        errors.append("experience table must be a non-empty dictionary")
        return {"valid": False, "errors": errors, "warnings": warnings, "summary": summary}

    required_road_ids = {str(item) for item in (required_road_ids or [])}
    missing_roads = sorted(required_road_ids - set(map(str, table)))
    if missing_roads:
        errors.append(f"required roads missing: {','.join(missing_roads)}")

    for raw_road_id, road_data in table.items():
        road_id = str(raw_road_id)
        summary["roads"] += 1
        if not isinstance(road_data, dict) or not road_data:
            errors.append(f"{road_id}: road data is empty or invalid")
            continue

        cross_config = None
        if cross_info is not None:
            cross_config = cross_info.get(road_id)
            if not isinstance(cross_config, dict):
                errors.append(f"{road_id}: missing cross_info configuration")
                continue

        for direction, time_map in road_data.items():
            summary["directions"] += 1
            if direction not in VALID_DIRECTIONS:
                errors.append(f"{road_id}/{direction}: invalid direction")
                continue
            if not isinstance(time_map, dict) or not time_map:
                errors.append(f"{road_id}/{direction}: direction has no time points")
                continue

            allowed_lanes = None
            if cross_config is not None:
                base_lanes, left_lanes = _configured_lane_sets(cross_config, direction)
                allowed_lanes = left_lanes if direction.endswith("TL") else base_lanes
                if direction.endswith("TL") and not left_lanes:
                    message = f"{road_id}/{direction}: no configured 1A lane"
                    (warnings if allow_legacy_records else errors).append(message)
                elif not allowed_lanes:
                    message = (
                        f"{road_id}/{direction}: no controlled capacity lane"
                    )
                    (warnings if allow_legacy_records else errors).append(message)

            for raw_green_time, vector in time_map.items():
                try:
                    green_time = int(raw_green_time)
                except (TypeError, ValueError):
                    errors.append(
                        f"{road_id}/{direction}/{raw_green_time}: invalid green time"
                    )
                    continue
                if not MIN_GREEN_TIME <= green_time <= MAX_GREEN_TIME:
                    message = (
                        f"{road_id}/{direction}/{green_time}: "
                        "green time outside 1..150"
                    )
                    if allow_legacy_records and green_time == 0:
                        warnings.append(message + " (legacy placeholder ignored)")
                    else:
                        errors.append(message)
                    continue
                try:
                    normalized = _normalize_vector(vector)
                except (TypeError, ValueError) as error:
                    errors.append(f"{road_id}/{direction}/{green_time}: {error}")
                    continue

                if allowed_lanes is not None:
                    invalid_nonzero_lanes = [
                        str(index)
                        for index, value in enumerate(normalized)
                        if value > 0 and index not in allowed_lanes
                    ]
                    if invalid_nonzero_lanes:
                        message = (
                            f"{road_id}/{direction}/{green_time}: nonzero flow outside "
                            f"configured lanes {','.join(invalid_nonzero_lanes)}"
                        )
                        (warnings if allow_legacy_records else errors).append(message)
                summary["points"] += 1
                summary["nonzero_lane_values"] += sum(
                    1 for value in normalized if value > 0
                )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
        "allow_legacy_records": bool(allow_legacy_records),
        "lane_policy": policy_metadata(),
    }


def validate_release_evidence(selection_report, completion_report, candidate_path=None):
    """Require the P80 selector and completion report to agree on their handoff."""
    errors = []
    if not isinstance(selection_report, dict):
        return {
            "valid": False,
            "errors": ["selection report is missing or invalid"],
            "selection_summary": {},
            "completion_summary": {},
        }
    if not isinstance(completion_report, dict):
        return {
            "valid": False,
            "errors": ["completion report is missing or invalid"],
            "selection_summary": selection_report.get("summary", {}),
            "completion_summary": {},
        }
    selection_summary = selection_report.get("summary", {})
    completion_summary = completion_report.get("summary", {})
    policy = selection_report.get("policy", {})

    if selection_report.get("selection") != "audit_gated_nearest_rank_percentile_per_lane":
        errors.append("selection report is not an audit-gated lane-level P80 result")
    if int(selection_summary.get("accepted_points", 0)) <= 0:
        errors.append("selection report contains no accepted points")
    if int(policy.get("min_sample_count", 0)) < 1:
        errors.append("selection report has no minimum sample gate")
    if int(policy.get("min_date_support", 0)) < 1:
        errors.append("selection report has no minimum date gate")
    if completion_report.get("completion_mode") != "preserve_trusted_points_interpolation":
        errors.append("completion report did not preserve trusted P80 points")
    if int(completion_summary.get("changed_source_points", -1)) != 0:
        errors.append("completion report changed trusted source points")
    if int(completion_summary.get("removed_source_points", -1)) != 0:
        errors.append("completion report removed trusted source points")
    if int(completion_summary.get("completed_points", 0)) < int(
        completion_summary.get("source_points", 0)
    ):
        errors.append("completion report lost points")

    selection_output = selection_report.get("output_path")
    completion_input = completion_report.get("input_path")
    if selection_output and completion_input:
        if os.path.normcase(os.path.abspath(selection_output)) != os.path.normcase(
            os.path.abspath(completion_input)
        ):
            errors.append("completion input does not match selection output")
    completion_output = completion_report.get("output_path")
    if candidate_path and completion_output:
        if os.path.normcase(os.path.abspath(candidate_path)) != os.path.normcase(
            os.path.abspath(completion_output)
        ):
            errors.append("release candidate does not match completion output")

    return {
        "valid": not errors,
        "errors": errors,
        "selection_summary": selection_summary,
        "completion_summary": completion_summary,
    }


def validate_bootstrap_completion_evidence(completion_report, candidate_path=None):
    """Validate the manual E_T -> preserve-only buqi bootstrap handoff."""
    errors = []
    if not isinstance(completion_report, dict):
        return {
            "valid": False,
            "errors": ["completion report is missing or invalid"],
            "completion_summary": {},
        }
    summary = completion_report.get("summary", {})
    if completion_report.get("completion_mode") != (
        "preserve_trusted_points_interpolation"
    ):
        errors.append("bootstrap buqi did not use preserve-only interpolation")
    changed_capacity_points = summary.get(
        "changed_source_capacity_points",
        summary.get("changed_source_points", -1),
    )
    if int(changed_capacity_points) != 0:
        errors.append("bootstrap buqi changed E_T source points")
    if int(summary.get("removed_source_points", -1)) != 0:
        errors.append("bootstrap buqi removed E_T source points")
    if int(summary.get("completed_points", 0)) < int(
        summary.get("source_points", 0)
    ):
        errors.append("bootstrap buqi lost E_T source points")
    completion_output = completion_report.get("output_path")
    if candidate_path and completion_output:
        if os.path.normcase(os.path.abspath(candidate_path)) != os.path.normcase(
            os.path.abspath(completion_output)
        ):
            errors.append("bootstrap candidate does not match completion output")
    return {
        "valid": not errors,
        "errors": errors,
        "completion_summary": summary,
    }


def release_bootstrap_experience_table(
    candidate_path,
    completion_report_path,
    runtime_path,
    cross_info_path,
    versions_dir,
    manifest_path=None,
    activate=False,
):
    """Manually validate and release the initial E_T + buqi table."""
    candidate_table = _load_json(candidate_path)
    completion_report = _load_json(completion_report_path)
    cross_info = _load_json(cross_info_path)
    table_validation = validate_experience_table(candidate_table, cross_info)
    evidence_validation = validate_bootstrap_completion_evidence(
        completion_report,
        candidate_path=candidate_path,
    )
    if not table_validation["valid"] or not evidence_validation["valid"]:
        errors = table_validation["errors"] + evidence_validation["errors"]
        raise ExperienceReleaseError("; ".join(errors))
    if not activate:
        return {
            "activated": False,
            "validation": {
                "table": table_validation,
                "completion": evidence_validation,
            },
            "candidate_table": candidate_table,
        }
    result = activate_validated_experience_table(
        table=candidate_table,
        runtime_path=runtime_path,
        cross_info_path=cross_info_path,
        versions_dir=versions_dir,
        manifest_path=manifest_path,
        release_kind="manual_bootstrap_et_buqi",
        source_metadata={
            "candidate_path": os.path.abspath(candidate_path),
            "completion_report_path": os.path.abspath(completion_report_path),
            "completion_summary": completion_report.get("summary", {}),
        },
    )
    result["validation"] = {
        "table": table_validation,
        "completion": evidence_validation,
    }
    return result


def merge_experience_tables(active_table, candidate_table, replace_road_ids=None):
    """Merge a pilot candidate without deleting unrelated production roads."""
    result = copy.deepcopy(active_table or {})
    replace_road_ids = {str(item) for item in (replace_road_ids or [])}
    updated_roads = []

    for raw_road_id, candidate_road in candidate_table.items():
        road_id = str(raw_road_id)
        updated_roads.append(road_id)
        if road_id in replace_road_ids:
            result[road_id] = copy.deepcopy(candidate_road)
            continue
        result.setdefault(road_id, {})
        for direction, time_map in candidate_road.items():
            result[road_id][direction] = copy.deepcopy(time_map)

    return result, sorted(updated_roads)


def _release_id(table):
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"experience_{timestamp}_{_canonical_hash(table)[:12]}"


def activate_validated_experience_table(
    table,
    runtime_path,
    cross_info_path,
    versions_dir,
    manifest_path=None,
    release_kind="validated_table",
    source_metadata=None,
    required_road_ids=None,
    allow_legacy_records=False,
):
    """Validate, version, and atomically activate a complete runtime table.

    This is the release entry for daily pool output. Bootstrap selector and
    completion evidence belong to the operator-controlled initial release and
    are deliberately not required for an already complete blended table.
    """
    cross_info = _load_json(cross_info_path)
    validation = validate_experience_table(
        table,
        cross_info,
        required_road_ids=required_road_ids,
        allow_legacy_records=allow_legacy_records,
    )
    if not validation["valid"]:
        raise ExperienceReleaseError("; ".join(validation["errors"]))

    active_table = _load_json(runtime_path, default={})
    versions_dir = os.path.abspath(versions_dir)
    if manifest_path is None:
        manifest_path = os.path.join(versions_dir, "active_manifest.json")
    previous_manifest = _load_json(manifest_path, default={})
    table_hash = _canonical_hash(table)
    active_hash = _canonical_hash(active_table) if active_table else None
    if active_hash == table_hash:
        return {
            "activated": False,
            "unchanged": True,
            "validation": validation,
            "manifest": previous_manifest,
        }

    release_id = _release_id(table)
    version_path = os.path.join(versions_dir, f"{release_id}.json")
    rollback_path = os.path.join(versions_dir, f"{release_id}_previous.json")
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runtime_path": os.path.abspath(runtime_path),
        "version_path": os.path.abspath(version_path),
        "rollback_version_path": os.path.abspath(rollback_path),
        "previous_release_id": previous_manifest.get("release_id"),
        "active_sha256": table_hash,
        "previous_sha256": active_hash,
        "release_kind": str(release_kind),
        "source_metadata": copy.deepcopy(source_metadata or {}),
        "validation_options": {
            "required_road_ids": sorted(
                str(item) for item in (required_road_ids or [])
            ),
            "allow_legacy_records": bool(allow_legacy_records),
        },
        "validation": validation,
        "activated": True,
    }

    if active_table:
        _write_json_atomic(rollback_path, active_table)
    _write_json_atomic(version_path, table)
    _write_json_atomic(runtime_path, table)
    _write_json_atomic(manifest_path, manifest)
    return {
        "activated": True,
        "unchanged": False,
        "validation": validation,
        "manifest": manifest,
    }


def release_experience_table(
    candidate_path,
    selection_report_path,
    completion_report_path,
    runtime_path,
    cross_info_path,
    versions_dir,
    manifest_path=None,
    replace_road_ids=None,
    activate=False,
):
    """Validate, version, and optionally atomically activate one experience table."""
    candidate_table = _load_json(candidate_path)
    selection_report = _load_json(selection_report_path)
    completion_report = _load_json(completion_report_path)
    cross_info = _load_json(cross_info_path)
    active_table = _load_json(runtime_path, default={})

    table_validation = validate_experience_table(candidate_table, cross_info)
    evidence_validation = validate_release_evidence(
        selection_report,
        completion_report,
        candidate_path=candidate_path,
    )
    if not table_validation["valid"] or not evidence_validation["valid"]:
        errors = table_validation["errors"] + evidence_validation["errors"]
        raise ExperienceReleaseError("; ".join(errors))

    merged_table, updated_roads = merge_experience_tables(
        active_table,
        candidate_table,
        replace_road_ids=replace_road_ids,
    )
    release_id = _release_id(merged_table)
    versions_dir = os.path.abspath(versions_dir)
    if manifest_path is None:
        manifest_path = os.path.join(versions_dir, "active_manifest.json")
    version_path = os.path.join(versions_dir, f"{release_id}.json")
    rollback_path = os.path.join(versions_dir, f"{release_id}_previous.json")
    previous_manifest = _load_json(manifest_path, default={})
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runtime_path": os.path.abspath(runtime_path),
        "version_path": os.path.abspath(version_path),
        "rollback_version_path": os.path.abspath(rollback_path),
        "previous_release_id": previous_manifest.get("release_id"),
        "candidate_path": os.path.abspath(candidate_path),
        "candidate_sha256": _canonical_hash(candidate_table),
        "active_sha256": _canonical_hash(merged_table),
        "updated_road_ids": updated_roads,
        "replace_road_ids": sorted(str(item) for item in (replace_road_ids or [])),
        "release_mode": "replace_roads" if replace_road_ids else "merge_directions",
        "selection_report_path": os.path.abspath(selection_report_path),
        "completion_report_path": os.path.abspath(completion_report_path),
        "validation": {
            "table": table_validation,
            "evidence": evidence_validation,
        },
        "activated": bool(activate),
    }

    if activate:
        if active_table:
            _write_json_atomic(rollback_path, active_table)
        _write_json_atomic(version_path, merged_table)
        _write_json_atomic(runtime_path, merged_table)
        _write_json_atomic(manifest_path, manifest)

    return {
        "activated": bool(activate),
        "manifest": manifest,
        "merged_table": merged_table,
    }


def rollback_experience_table(runtime_path, manifest_path, cross_info_path):
    """Restore the pre-release snapshot recorded by the active release manifest."""
    manifest = _load_json(manifest_path)
    rollback_path = manifest.get("rollback_version_path") if isinstance(manifest, dict) else None
    if not rollback_path or not os.path.exists(rollback_path):
        raise ExperienceReleaseError("active manifest has no recoverable rollback version")

    table = _load_json(rollback_path)
    validation_options = manifest.get("validation_options", {})
    validation = validate_experience_table(
        table,
        _load_json(cross_info_path),
        required_road_ids=validation_options.get("required_road_ids"),
        allow_legacy_records=bool(
            validation_options.get("allow_legacy_records", False)
        ),
    )
    if not validation["valid"]:
        raise ExperienceReleaseError("rollback table invalid: " + "; ".join(validation["errors"]))

    _write_json_atomic(runtime_path, table)
    manifest["rolled_back_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest["active_sha256"] = _canonical_hash(table)
    manifest["rollback_applied"] = True
    _write_json_atomic(manifest_path, manifest)
    return {"runtime_path": os.path.abspath(runtime_path), "validation": validation}


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--candidate", required=True)
    release_parser.add_argument("--selection-report", required=True)
    release_parser.add_argument("--completion-report", required=True)
    release_parser.add_argument("--runtime", required=True)
    release_parser.add_argument("--cross-info", required=True)
    release_parser.add_argument("--versions-dir", required=True)
    release_parser.add_argument("--manifest")
    release_parser.add_argument("--replace-road", action="append", default=[])
    release_parser.add_argument("--activate", action="store_true")

    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--candidate", required=True)
    bootstrap_parser.add_argument("--completion-report", required=True)
    bootstrap_parser.add_argument("--runtime", required=True)
    bootstrap_parser.add_argument("--cross-info", required=True)
    bootstrap_parser.add_argument("--versions-dir", required=True)
    bootstrap_parser.add_argument("--manifest")
    bootstrap_parser.add_argument("--activate", action="store_true")

    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("--runtime", required=True)
    rollback_parser.add_argument("--manifest", required=True)
    rollback_parser.add_argument("--cross-info", required=True)

    args = parser.parse_args()
    try:
        if args.command == "release":
            result = release_experience_table(
                candidate_path=args.candidate,
                selection_report_path=args.selection_report,
                completion_report_path=args.completion_report,
                runtime_path=args.runtime,
                cross_info_path=args.cross_info,
                versions_dir=args.versions_dir,
                manifest_path=args.manifest,
                replace_road_ids=args.replace_road,
                activate=args.activate,
            )
            print(json.dumps(result["manifest"], ensure_ascii=False, indent=2))
        elif args.command == "bootstrap":
            result = release_bootstrap_experience_table(
                candidate_path=args.candidate,
                completion_report_path=args.completion_report,
                runtime_path=args.runtime,
                cross_info_path=args.cross_info,
                versions_dir=args.versions_dir,
                manifest_path=args.manifest,
                activate=args.activate,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(
                rollback_experience_table(
                    runtime_path=args.runtime,
                    manifest_path=args.manifest,
                    cross_info_path=args.cross_info,
                ),
                ensure_ascii=False,
                indent=2,
            ))
    except ExperienceReleaseError as error:
        parser.error(str(error))


if __name__ == "__main__":
    _main()
