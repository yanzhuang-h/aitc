"""Server-owned daily experience-pool accumulation and table update.

The initial E_T training and buqi completion are intentionally absent here.
This module only processes T-2 operational logs while Server_AITC is running.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
import threading

from lib.data_ANS.experience_pool import (
    DEFAULT_DENSE_CLUSTER_FRACTION,
    DEFAULT_POOL_SELECTION_METHOD,
    _candidate_sample_count,
    _load_json,
    _write_json_atomic,
    run_daily_pool_update,
)
from lib.data_ANS.experience_release import (
    activate_validated_experience_table,
    validate_experience_table,
)
from lib.data_ANS.raw_feedback_normalizer import (
    build_near_capacity_candidate_samples,
    normalize_raw_feedback,
)


LOGGER = logging.getLogger("ExperiencePoolRuntime")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = PROJECT_ROOT / "lib"
LOGS_DIR = PROJECT_ROOT / "logs_data"
# Persistent pool memory belongs with the deployed model assets. Large daily
# diagnostics remain under logs_data and can be cleaned independently.
DEFAULT_STATE_DIR = LIB_DIR / "experience_pool"
DEFAULT_ARTIFACT_DIR = LOGS_DIR / "experience_pool" / "daily"
DEFAULT_MIN_SAMPLE_COUNT = 30
DEFAULT_SOURCE_DAY_DELAY = 2
DEFAULT_DAILY_RUN_TIME = dt.time(12, 0)
# Optional live-test trigger. Set this environment variable to 300 to run T-2
# once five minutes after server startup; zero retains only daily noon runs.
DEFAULT_INITIAL_DELAY_SECONDS = 0
DEFAULT_POOL_COLLECTION_ROAD_IDS = frozenset({
    "1300086",
    "1300364",
    "1300179",
    "1300108",
    "1300120",
    "1300230",
    "1300089",
    "1300255",
    "1300039",
    "1300253",
    "1300094",
    "1300358",
    "1300067",
    "1300070",
    "1300266",
    "1700262",
    "1700085",
    "1700067",
    "1700293",
    "1300362",
    "1300087",
    "1300147",
    "1700124",
    "1700125",
})
DEFAULT_TABLE_UPDATE_ROAD_IDS = frozenset({
    "1700125",
    "1300069",
    "1300068",
    "1300070",
})


def _read_bool_env(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _configured_path(name, default):
    return Path(os.environ.get(name, str(default))).resolve()


def _configured_road_ids(environment_name, defaults):
    configured = os.environ.get(environment_name, "").strip()
    if configured:
        return {
            item.strip()
            for item in configured.split(",")
            if item.strip()
        }
    return {str(road_id) for road_id in defaults}


def _configured_collection_roads():
    # Update roads are always collected as well; otherwise a road selected for
    # table updates could never accumulate the evidence needed to update it.
    collection_roads = _configured_road_ids(
        "AITC_EXPERIENCE_POOL_ROADS",
        DEFAULT_POOL_COLLECTION_ROAD_IDS,
    )
    return sorted(collection_roads | _configured_update_roads())


def _configured_update_roads():
    return _configured_road_ids(
        "AITC_EXPERIENCE_TABLE_UPDATE_ROADS",
        DEFAULT_TABLE_UPDATE_ROAD_IDS,
    )


def _configured_roads(active_table=None):
    """Return the collection scope; ``active_table`` is kept for old callers."""
    return _configured_collection_roads()


def _source_day_bounds(source_date):
    local_tz = dt.datetime.now().astimezone().tzinfo
    start = dt.datetime.combine(source_date, dt.time.min, tzinfo=local_tz)
    end = start + dt.timedelta(days=1) - dt.timedelta(seconds=1)
    return int(start.timestamp()), int(end.timestamp())


def _run_paths(source_date):
    source_date_text = source_date.isoformat()
    state_dir = _configured_path(
        "AITC_EXPERIENCE_POOL_STATE_DIR",
        DEFAULT_STATE_DIR,
    )
    artifact_root = _configured_path(
        "AITC_EXPERIENCE_POOL_ARTIFACT_DIR",
        DEFAULT_ARTIFACT_DIR,
    )
    artifact_dir = artifact_root / source_date_text
    return {
        "state_dir": state_dir,
        "artifact_dir": artifact_dir,
        "run_manifest": state_dir / "runs" / f"{source_date_text}.json",
        "flow": LOGS_DIR / "flow" / f"{source_date_text}_flow.txt",
        "extend": LOGS_DIR / "extend" / f"{source_date_text}_extend.txt",
        "queue": LOGS_DIR / "queue" / f"{source_date_text}_queue.txt",
        "observations": artifact_dir / "observations.json",
        "normalization_report": artifact_dir / "normalization_report.json",
        "candidates": artifact_dir / "near_capacity_candidates.json",
        "pool_report": artifact_dir / "pool_update_report.json",
        "full_pool": state_dir / "experience_pool_full.json",
        "rolling_table": state_dir / "rolling_experience_table.json",
    }


def _existing_terminal_manifest(path):
    manifest = _load_json(str(path), default={})
    if not isinstance(manifest, dict):
        return None
    status = str(manifest.get("status", ""))
    if status.startswith("completed") or status.startswith("skipped"):
        return manifest
    return None


def run_experience_pool_day(source_date):
    """Process one T-2 source date exactly once and conditionally release."""
    if isinstance(source_date, str):
        source_date = dt.date.fromisoformat(source_date)
    if not isinstance(source_date, dt.date):
        raise TypeError("source_date must be a date or ISO date string")

    paths = _run_paths(source_date)
    terminal = _existing_terminal_manifest(paths["run_manifest"])
    if terminal is not None:
        return terminal

    source_date_text = source_date.isoformat()
    base_report = {
        "schema_version": 1,
        "source_date": source_date_text,
        "triggered_at": dt.datetime.now().astimezone().isoformat(),
        "source_day_delay": DEFAULT_SOURCE_DAY_DELAY,
    }
    missing_files = [
        str(paths[name])
        for name in ("flow", "extend")
        if not paths[name].is_file()
    ]
    if missing_files:
        report = {
            **base_report,
            "status": "skipped_missing_source_data",
            "missing_files": missing_files,
            "pool_committed": False,
            "table_updated": False,
        }
        _write_json_atomic(str(paths["run_manifest"]), report)
        return report

    runtime_path = _configured_path(
        "AITC_EXPERIENCE_RUNTIME_TABLE",
        DEFAULT_STATE_DIR / "new_wwx.json",
    )
    cross_info_path = _configured_path(
        "AITC_EXPERIENCE_CROSS_INFO",
        LIB_DIR / "cross_info.json",
    )
    active_table = _load_json(str(runtime_path), default={})
    cross_info = _load_json(str(cross_info_path), default={})
    update_roads = _configured_update_roads()
    active_validation = validate_experience_table(
        active_table,
        cross_info,
        required_road_ids=update_roads,
        allow_legacy_records=True,
    )
    if not active_validation["valid"]:
        report = {
            **base_report,
            "status": "skipped_invalid_active_table",
            "active_table": str(runtime_path),
            "validation": active_validation,
            "pool_committed": False,
            "table_updated": False,
        }
        _write_json_atomic(str(paths["run_manifest"]), report)
        return report

    target_roads = _configured_roads(active_table)
    missing_crosses = sorted(set(target_roads) - set(cross_info))
    if missing_crosses:
        report = {
            **base_report,
            "status": "skipped_missing_cross_configuration",
            "missing_crosses": missing_crosses,
            "pool_committed": False,
            "table_updated": False,
        }
        _write_json_atomic(str(paths["run_manifest"]), report)
        return report

    start_time, end_time = _source_day_bounds(source_date)
    queue_path = str(paths["queue"]) if paths["queue"].is_file() else None
    observations, normalization_report = normalize_raw_feedback(
        flow_path=str(paths["flow"]),
        extend_path=str(paths["extend"]),
        queue_path=queue_path,
        cross_info=cross_info,
        source_date=source_date_text,
        start_time=start_time,
        end_time=end_time,
        target_cross_ids=target_roads,
    )
    candidates, conversion_stats = build_near_capacity_candidate_samples(
        observations
    )
    normalization_report["candidate_conversion"] = conversion_stats
    _write_json_atomic(str(paths["observations"]), observations)
    _write_json_atomic(
        str(paths["normalization_report"]),
        normalization_report,
    )
    _write_json_atomic(str(paths["candidates"]), candidates)

    candidate_count = _candidate_sample_count(candidates)
    if candidate_count == 0:
        report = {
            **base_report,
            "status": "completed_no_qualified_samples",
            "target_road_ids": target_roads,
            "pool_collection_road_ids": target_roads,
            "table_update_road_ids": sorted(update_roads),
            "observation_count": len(observations),
            "candidate_count": 0,
            "pool_committed": False,
            "table_updated": False,
            "artifacts": {
                "observations": str(paths["observations"]),
                "normalization_report": str(paths["normalization_report"]),
                "candidates": str(paths["candidates"]),
            },
        }
        _write_json_atomic(str(paths["run_manifest"]), report)
        return report

    minimum_samples = int(
        os.environ.get(
            "AITC_EXPERIENCE_POOL_MIN_SAMPLES",
            DEFAULT_MIN_SAMPLE_COUNT,
        )
    )
    selection_method = os.environ.get(
        "AITC_EXPERIENCE_POOL_SELECTION_METHOD",
        DEFAULT_POOL_SELECTION_METHOD,
    ).strip().lower()
    cluster_fraction = float(
        os.environ.get(
            "AITC_EXPERIENCE_POOL_CLUSTER_FRACTION",
            DEFAULT_DENSE_CLUSTER_FRACTION,
        )
    )
    updated_table, pool_report = run_daily_pool_update(
        candidate_samples_path=str(paths["candidates"]),
        full_pool_path=str(paths["full_pool"]),
        old_table_path=str(runtime_path),
        output_path=str(paths["rolling_table"]),
        report_path=str(paths["pool_report"]),
        min_sample_count=minimum_samples,
        update_road_ids=update_roads,
        authoritative_old_table=True,
        selection_method=selection_method,
        cluster_fraction=cluster_fraction,
    )
    changed_lanes = int(
        pool_report.get("blend", {}).get("lane_values_changed", 0)
    )
    release_result = None
    if changed_lanes > 0:
        versions_dir = _configured_path(
            "AITC_EXPERIENCE_VERSIONS_DIR",
            LIB_DIR / "experience_versions",
        )
        manifest_path = _configured_path(
            "AITC_EXPERIENCE_MANIFEST",
            versions_dir / "active_manifest.json",
        )
        release_result = activate_validated_experience_table(
            table=updated_table,
            runtime_path=str(runtime_path),
            cross_info_path=str(cross_info_path),
            versions_dir=str(versions_dir),
            manifest_path=str(manifest_path),
            release_kind="daily_experience_pool",
            required_road_ids=update_roads,
            allow_legacy_records=True,
            source_metadata={
                "source_date": source_date_text,
                "candidate_count": candidate_count,
                "minimum_sample_count": minimum_samples,
                "selection_method": selection_method,
                "cluster_fraction": cluster_fraction,
                "pool_report": str(paths["pool_report"]),
            },
        )

    report = {
        **base_report,
        "status": (
            "completed_table_updated"
            if release_result and release_result.get("activated")
            else "completed_pool_updated_no_table_change"
        ),
        "target_road_ids": target_roads,
        "pool_collection_road_ids": target_roads,
        "table_update_road_ids": sorted(update_roads),
        "observation_count": len(observations),
        "candidate_count": candidate_count,
        "minimum_sample_count": minimum_samples,
        "selection_method": selection_method,
        "cluster_fraction": cluster_fraction,
        "pool_committed": True,
        "table_updated": bool(
            release_result and release_result.get("activated")
        ),
        "pool_summary": pool_report,
        "release": (
            release_result.get("manifest") if release_result else None
        ),
        "artifacts": {
            "observations": str(paths["observations"]),
            "normalization_report": str(paths["normalization_report"]),
            "candidates": str(paths["candidates"]),
            "pool_report": str(paths["pool_report"]),
            "full_pool": str(paths["full_pool"]),
            "rolling_table": str(paths["rolling_table"]),
        },
    }
    _write_json_atomic(str(paths["run_manifest"]), report)
    return report


class ExperiencePoolScheduler:
    """Server-owned scheduler with an optional initial run and noon runs."""

    def __init__(self, logger=None):
        self.logger = logger or LOGGER
        self._stop_event = threading.Event()
        self._thread = None
        self._run_lock = threading.Lock()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="experience-pool-daily-noon",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    @staticmethod
    def source_date_for_run(run_date):
        return run_date - dt.timedelta(days=DEFAULT_SOURCE_DAY_DELAY)

    @staticmethod
    def seconds_until_next_daily_run(now=None):
        now = now or dt.datetime.now().astimezone()
        next_run = dt.datetime.combine(
            now.date(),
            DEFAULT_DAILY_RUN_TIME,
            tzinfo=now.tzinfo,
        )
        if next_run <= now:
            next_run += dt.timedelta(days=1)
        return max(0.0, (next_run - now).total_seconds())

    @staticmethod
    def initial_delay_seconds():
        raw_value = os.environ.get(
            "AITC_EXPERIENCE_POOL_INITIAL_DELAY_SECONDS",
            str(DEFAULT_INITIAL_DELAY_SECONDS),
        )
        try:
            return max(0.0, float(raw_value))
        except (TypeError, ValueError):
            return float(DEFAULT_INITIAL_DELAY_SECONDS)

    def run_for_date(self, run_date=None, source_date=None):
        if source_date is None:
            run_date = run_date or dt.datetime.now().astimezone().date()
            source_date = self.source_date_for_run(run_date)
        elif isinstance(source_date, str):
            source_date = dt.date.fromisoformat(source_date)
        if not self._run_lock.acquire(blocking=False):
            self.logger.warning("Experience pool daily task is already running")
            return None
        try:
            report = run_experience_pool_day(source_date)
            self.logger.info(
                "Experience pool daily task finished: source_date=%s status=%s",
                source_date,
                report.get("status"),
            )
            return report
        except Exception:
            self.logger.exception(
                "Experience pool daily task failed: source_date=%s",
                source_date,
            )
            return None
        finally:
            self._run_lock.release()

    def _run_loop(self):
        initial_delay = self.initial_delay_seconds()
        if initial_delay > 0:
            self.logger.info(
                "Experience pool initial T-2 test run scheduled in %.0f seconds",
                initial_delay,
            )
            if self._stop_event.wait(initial_delay):
                return
            test_source_date = os.environ.get(
                "AITC_EXPERIENCE_POOL_TEST_SOURCE_DATE",
                "",
            ).strip()
            self.run_for_date(source_date=test_source_date or None)

        while not self._stop_event.is_set():
            wait_seconds = self.seconds_until_next_daily_run()
            if self._stop_event.wait(wait_seconds):
                return
            self.run_for_date()


def start_experience_pool_scheduler(logger=None):
    if not _read_bool_env("AITC_EXPERIENCE_POOL_ENABLED", default=True):
        (logger or LOGGER).info("Experience pool scheduler is disabled")
        return None
    scheduler = ExperiencePoolScheduler(logger=logger)
    scheduler.start()
    return scheduler
