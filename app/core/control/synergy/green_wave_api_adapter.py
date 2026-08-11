"""绿波接口格式适配层（文档1 ↔ 文档2）。

背景：
- 文档2（绿波接口说明文档）：Python 函数（``lib.green_wave_functions``）使用
  ``corridor`` 结构（corridor_id / intersections / periods / road_junction / topology），
  内部生产链路（Global / lvbotest）依赖此结构。
- 文档1（绿波路段配置接口说明）：外方 HTTP 调用使用 ``segment_id + green_wave_info``
  请求结构与 ``items + message`` 响应结构。

本层只做格式双向转换，不修改 lib，也不参与绿波计算。
"""

from __future__ import annotations

from typing import Any, Mapping

# 文档1 返回示例中的配置文件路径（按部署位置统一为 corridors）
CONFIG_FILE = "lib/green_wave_corridors.json"

# 文档1 未提供但 corridor 必须的默认值（与现有 lvbo_01 配置保持一致）
DEFAULT_CYCLE_SECONDS = 90
DEFAULT_GREEN_STAGE_INDEX = 0
DEFAULT_BALANCE_STAGE_INDEX = 1
DEFAULT_RED_SECONDS = 0


def is_doc1_payload(payload: Mapping[str, Any]) -> bool:
    """判断是否为文档1 的请求结构（segment_id + green_wave_info）。"""
    return (
        isinstance(payload, dict)
        and "segment_id" in payload
        and isinstance(payload.get("green_wave_info"), dict)
    )


def doc1_to_corridor(payload: Mapping[str, Any]) -> dict[str, Any]:
    """文档1 请求（segment_id/green_wave_info）→ 文档2 corridor 结构。

    字段映射：
    - segment_id → corridor_id；segment_name → name
    - green_wave_info.ORDER → intersections（green/balance 阶段与红灯默认 0/1/0）
    - LEFT_TARGET_OFFSET_MAP + LEFT_OFFSET_RID + ORDER 正向 → direction=L 的时段
    - RIGHT_TARGET_OFFSET_MAP + RIGHT_OFFSET_RID + ORDER 反向 → direction=R 的时段
    - morning/evening_peak_trigger 的 start/end → 对应时段起止
    - road_junction / topology 原样保留
    """
    segment_id = str(payload.get("segment_id", "")).strip()
    if not segment_id:
        raise ValueError("segment_id 不能为空")
    info = payload.get("green_wave_info")
    if not isinstance(info, dict):
        raise ValueError("green_wave_info 必须是 JSON 对象")

    # 文档1 未定义 enabled；允许在请求顶层携带可选布尔控制（默认启用）。
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是 bool")

    order = info.get("ORDER")
    if not isinstance(order, list) or len(order) < 2:
        raise ValueError("green_wave_info.ORDER 必须是至少包含两个路口的数组")
    order = [str(item).strip() for item in order]

    intersections = [
        {
            "cross_id": cross_id,
            "green_stage_index": DEFAULT_GREEN_STAGE_INDEX,
            "balance_stage_index": DEFAULT_BALANCE_STAGE_INDEX,
            "default_red_seconds": DEFAULT_RED_SECONDS,
        }
        for cross_id in order
    ]

    periods = []
    for period_id, trigger_key in (
        ("morning", "morning_peak_trigger"),
        ("evening", "evening_peak_trigger"),
    ):
        trigger = info.get(trigger_key)
        if not isinstance(trigger, dict):
            continue
        direction = str(trigger.get("direction", "")).strip().upper()
        start_time = str(trigger.get("start", "")).strip()
        end_time = str(trigger.get("end", "")).strip()
        if direction not in ("L", "R") or not start_time or not end_time:
            raise ValueError(
                f"{trigger_key} 需要 start、end 和 direction(L 或 R)"
            )

        if direction == "L":
            reference = str(info.get("LEFT_OFFSET_RID", "")).strip()
            raw_offsets = info.get("LEFT_TARGET_OFFSET_MAP") or {}
            period_order = list(order)
        else:
            reference = str(info.get("RIGHT_OFFSET_RID", "")).strip()
            raw_offsets = info.get("RIGHT_TARGET_OFFSET_MAP") or {}
            period_order = list(reversed(order))

        if not reference:
            raise ValueError(f"{trigger_key} 方向缺少对应的 OFFSET_RID")

        travel_seconds = {}
        for cross_id in period_order:
            raw = raw_offsets.get(cross_id)
            if raw is None:
                raise ValueError(
                    f"{trigger_key} 方向的 TARGET_OFFSET_MAP 缺少路口 {cross_id}"
                )
            travel_seconds[cross_id] = int(str(raw).strip())

        periods.append({
            "period_id": period_id,
            "start_time": start_time,
            "end_time": end_time,
            "reference_cross_id": reference,
            "intersection_order": period_order,
            "travel_seconds": travel_seconds,
        })

    if not periods:
        raise ValueError("green_wave_info 缺少 morning_peak_trigger/evening_peak_trigger")

    return {
        "corridor_id": segment_id,
        "name": str(payload.get("segment_name") or segment_id).strip() or segment_id,
        "enabled": enabled,
        "cycle_seconds": DEFAULT_CYCLE_SECONDS,
        "offset_step_seconds": 3,
        "minimum_remaining_green_seconds": 10,
        "simulation_target_elapsed_green_seconds": 10,
        "cooldown_seconds": 85,
        "intersections": intersections,
        "periods": periods,
        "road_junction": info.get("road_junction") or {},
        "topology": info.get("topology") or {},
    }


# ---------------------------------------------------------------------------
# 响应适配：文档2 函数返回 → 文档1 HTTP 响应
# ---------------------------------------------------------------------------


def adapt_save_result(result: Mapping[str, Any], fallback_segment_id: str = "") -> dict[str, Any]:
    """把 save_green_wave_corridor_config 返回转成文档1 的 validate/update 格式。"""
    if result.get("status") == "error":
        return {
            "status": "error",
            "saved": False,
            "reason": str(result.get("reason", "未知错误")),
        }
    dry_run = result.get("status") == "validated"
    saved = bool(result.get("saved", not dry_run))
    return {
        "status": "validated" if dry_run else "success",
        "saved": saved,
        "message": "validation success" if dry_run else "save success",
        "items": [
            {
                "segment_id": str(result.get("corridor_id") or fallback_segment_id),
                "saved": saved,
                "file": {
                    "path": CONFIG_FILE,
                    "operation": str(result.get("operation", "updated")),
                },
            }
        ],
    }


def adapt_list_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """列表返回：保持 items，并为每条补 segment_id 别名（文档1 命名）。"""
    if result.get("status") == "error":
        return {
            "status": "error",
            "saved": False,
            "reason": str(result.get("reason", "未知错误")),
        }
    items = []
    for item in result.get("items", []):
        normalized = dict(item)
        normalized.setdefault("segment_id", normalized.get("corridor_id"))
        items.append(normalized)
    return {
        "status": "success",
        "saved": False,
        "operation": "listed",
        "items": items,
    }


def adapt_get_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """单条查询返回：corridor 保留，并补 segment_id 别名。"""
    if result.get("status") == "error":
        return {
            "status": "error",
            "saved": False,
            "reason": str(result.get("reason", "未知错误")),
        }
    corridor = dict(result.get("corridor") or {})
    corridor.setdefault("segment_id", corridor.get("corridor_id"))
    return {
        "status": "success",
        "saved": False,
        "operation": "queried",
        "corridor": corridor,
    }


def adapt_enabled_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """启停/删除返回：保持原结构，补 message 与 segment_id 别名。"""
    if result.get("status") == "error":
        return {
            "status": "error",
            "saved": False,
            "reason": str(result.get("reason", "未知错误")),
        }
    adapted = dict(result)
    adapted["message"] = str(result.get("operation", ""))
    adapted.setdefault("segment_id", result.get("corridor_id"))
    return adapted
