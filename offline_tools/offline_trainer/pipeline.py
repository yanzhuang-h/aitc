"""独立离线训练模块 - 核心流水线编排器 (Pipeline Orchestrator).

闭环串联预检、数据清洗、E_T 容量估算、buqi 单调补气插值、Schema 校验与无损合并。
完全自包含，零外部模块依赖，仅基于 Python 原生标准库。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .capacity_estimator import estimate_capacity_experience
from .interpolator import run_buqi_completion
from .validator import (
    ExperienceValidationError,
    merge_experience_tables,
    validate_experience_table,
)

LOGGER = logging.getLogger("OfflineTrainer.Pipeline")


def _write_json_atomic(path: str | Path, data: Any) -> None:
    """原子写入 JSON 文件，避免并发读写竞争。"""
    path_obj = Path(path).resolve()
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path_obj.parent),
            delete=False,
        ) as file:
            temp_path = file.name
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, str(path_obj))
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _load_json(path: str | Path, default: Any = None) -> Any:
    """加载 JSON 文件。"""
    path_obj = Path(path)
    if not path_obj.is_file():
        return default
    with open(path_obj, "r", encoding="utf-8") as file:
        return json.load(file)


def resolve_date_list(
    *,
    dates_arg: Optional[str] = None,
    days_arg: Optional[int] = None,
    reference_date: Optional[dt.date] = None,
) -> List[str]:
    """解析日期列表。支持日期区间 2026-07-01:2026-07-14、逗号分隔或倒推天数。"""
    if dates_arg:
        dates_arg = dates_arg.strip()
        if ":" in dates_arg:
            parts = [p.strip() for p in dates_arg.split(":") if p.strip()]
            if len(parts) != 2:
                raise ValueError(f"日期区间格式错误: {dates_arg}，正确格式如 2026-07-01:2026-07-14")
            start = dt.date.fromisoformat(parts[0])
            end = dt.date.fromisoformat(parts[1])
            if start > end:
                raise ValueError(f"起始日期不能晚于结束日期: {start} > {end}")
            curr = start
            resolved = []
            while curr <= end:
                resolved.append(curr.isoformat())
                curr += dt.timedelta(days=1)
            return resolved
        elif "," in dates_arg:
            return sorted({p.strip() for p in dates_arg.split(",") if p.strip()})
        else:
            return [dates_arg]

    days = days_arg if days_arg is not None else 14
    if days <= 0:
        raise ValueError(f"训练天数必须大于 0: days={days}")
    today = reference_date or dt.date.today()
    yesterday = today - dt.timedelta(days=1)
    resolved = [
        (yesterday - dt.timedelta(days=offset)).isoformat()
        for offset in reversed(range(days))
    ]
    return resolved


def check_input_data_availability(
    dates: Sequence[str],
    logs_dir: Path,
) -> Tuple[List[str], Dict[str, Dict[str, bool]]]:
    """检查指定日期的 flow 与 extend 日志文件是否存在。"""
    available_dates: List[str] = []
    details: Dict[str, Dict[str, bool]] = {}

    for date_str in dates:
        flow_path = logs_dir / "flow" / f"{date_str}_flow.txt"
        extend_path = logs_dir / "extend" / f"{date_str}_extend.txt"
        flow_ok = flow_path.is_file()
        extend_ok = extend_path.is_file()
        details[date_str] = {
            "flow": flow_ok,
            "extend": extend_ok,
            "flow_path": str(flow_path),
            "extend_path": str(extend_path),
        }
        if flow_ok and extend_ok:
            available_dates.append(date_str)

    return available_dates, details


def run_offline_pipeline(
    *,
    road_ids: Sequence[str],
    dates: Sequence[str],
    logs_dir: Path,
    cross_info_path: Path,
    output_dir: Path,
    target_table_path: Path,
    merge_to_online: bool = False,
    backup: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """执行完全自包含的离线冷启动训练流水线。"""
    started_at = dt.datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 预检配置与路口合法性
    cross_info = _load_json(cross_info_path)
    if not cross_info:
        raise ValueError(f"cross_info.json 为空或不存在: {cross_info_path}")

    target_roads = sorted({str(r).strip() for r in road_ids if str(r).strip()})
    if not target_roads:
        raise ValueError("请至少指定一个需要离线训练的目标路口 (--roads)")

    unknown_roads = sorted(set(target_roads) - set(cross_info))
    if unknown_roads:
        raise ValueError(f"cross_info.json 中不存在以下路口: {unknown_roads}")

    # 2. 检查日志完备性
    available_dates, file_details = check_input_data_availability(dates, logs_dir)

    precheck_summary = {
        "requested_roads": target_roads,
        "requested_dates_count": len(dates),
        "available_dates_count": len(available_dates),
        "available_dates": available_dates,
        "missing_dates": [d for d in dates if d not in available_dates],
        "file_details": file_details,
    }

    if dry_run:
        LOGGER.info("[Dry Run] 预检完成，不执行实际算法训练。")
        return {
            "status": "dry_run_success",
            "precheck": precheck_summary,
        }

    if not available_dates:
        raise FileNotFoundError(
            f"指定的全部 {len(dates)} 天均缺失完整的 flow/extend 日志，无法执行训练！"
        )

    if len(available_dates) < len(dates):
        LOGGER.warning(
            "部分日期日志缺失 (请求 %d 天，可用 %d 天，缺失 %d 天)，将仅使用可用日期继续训练",
            len(dates),
            len(available_dates),
            len(dates) - len(available_dates),
        )

    # 3. 阶段一：通行能力特征提取 (E_T 计算)
    LOGGER.info("── 阶段一：开始周期特征提取与通行能力估算 (E_T) ──")
    raw_et_output_path = output_dir / "raw_et_candidate_table.json"
    raw_experience, et_training_report = estimate_capacity_experience(
        road_ids=target_roads,
        dates=available_dates,
        logs_dir=str(logs_dir),
        cross_info=cross_info,
        output_path=str(raw_et_output_path),
        reset_output=True,
        verbose=verbose,
    )
    LOGGER.info("阶段一完成，原始候选经验表已保存至: %s", raw_et_output_path)

    # 4. 阶段二：单调插值补气 (Preserve-only 单调平滑)
    LOGGER.info("── 阶段二：开始缺失绿灯秒数可信单调插值 (buqi) ──")
    buqi_output_path = output_dir / "completed_experience_table.json"
    buqi_report_path = output_dir / "completion_report.json"
    completed_experience, completion_report = run_buqi_completion(
        data=raw_experience,
        cross_info=cross_info,
        road_ids=target_roads,
        output_path=str(buqi_output_path),
        report_path=str(buqi_report_path),
        output_selected_only=True,
    )
    LOGGER.info("阶段二完成，补齐后的经验表已保存至: %s", buqi_output_path)

    # 5. 阶段三：经验表合法性验证
    LOGGER.info("── 阶段三：对补齐成果进行 Schema 与拓扑合规校验 ──")
    validation_result = validate_experience_table(
        table=completed_experience,
        cross_info=cross_info,
        required_road_ids=target_roads,
        allow_legacy_records=False,
    )
    if not validation_result["valid"]:
        error_msg = f"经验表校验未通过: {'; '.join(validation_result.get('errors', []))}"
        LOGGER.error(error_msg)
        raise ExperienceValidationError(error_msg)
    LOGGER.info("阶段三合规校验通过。")

    # 6. 阶段四：安全发布与合并至生产底表 (可选)
    merge_result: Optional[Dict[str, Any]] = None
    if merge_to_online:
        LOGGER.info("── 阶段四：无损合并成果到生产底表: %s ──", target_table_path)
        active_table = _load_json(target_table_path, default={})
        target_table_path.parent.mkdir(parents=True, exist_ok=True)

        backup_path = None
        if backup and target_table_path.is_file():
            timestamp_str = started_at.strftime("%Y%m%d_%H%M%S")
            backup_path = target_table_path.parent / f"{target_table_path.name}.bak_{timestamp_str}"
            shutil.copy2(target_table_path, backup_path)
            LOGGER.info("已生成生产底表安全备份: %s", backup_path)

        merged_table, updated_roads = merge_experience_tables(
            active_table=active_table,
            candidate_table=completed_experience,
            replace_road_ids=target_roads,
        )

        _write_json_atomic(target_table_path, merged_table)
        LOGGER.info(
            "生产底表合并完成！更新/新增路口: %s，生产表路口总数: %d -> %d",
            updated_roads,
            len(active_table),
            len(merged_table),
        )

        # 确保别名软链接同步存在
        for alias_name in ("offline_pool.json", "offline_poll.json", "offline_poll.josn", "new_wwx.json"):
            alias_path = target_table_path.parent / alias_name
            if not alias_path.exists():
                try:
                    alias_path.symlink_to(target_table_path.name)
                except OSError:
                    pass

        merge_result = {
            "target_table": str(target_table_path),
            "backup_path": str(backup_path) if backup_path else None,
            "updated_roads": updated_roads,
            "total_roads_before": len(active_table),
            "total_roads_after": len(merged_table),
        }

    # 7. 生成全局离线训练清单 Manifest
    elapsed_seconds = (dt.datetime.now() - started_at).total_seconds()
    manifest = {
        "status": "success",
        "started_at": started_at.isoformat(),
        "finished_at": dt.datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "target_roads": target_roads,
        "trained_dates": available_dates,
        "merge_to_online": merge_to_online,
        "artifacts": {
            "output_dir": str(output_dir),
            "raw_candidate_table": str(raw_et_output_path),
            "completed_experience_table": str(buqi_output_path),
            "completion_report": str(buqi_report_path),
        },
        "precheck": precheck_summary,
        "validation": validation_result,
        "merge_result": merge_result,
    }
    manifest_path = output_dir / "offline_training_manifest.json"
    _write_json_atomic(manifest_path, manifest)
    LOGGER.info("离线训练流水线执行完成！清单文件: %s", manifest_path)
    return manifest
