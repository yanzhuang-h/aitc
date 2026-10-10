"""全局协调后的确定性安全门，不依赖模型或共享路口决策状态。"""

from __future__ import annotations

import copy
import logging
import math
import re
import time
from typing import Any, Callable

from pydantic import ValidationError

from .adapters import signal_plan_from_legacy, signal_plan_to_legacy
from .safety_schemas import PlanSafetyResult


class ControlSafetyEngine:
    """保留既有时长修正；结构错误与修正后仍不合法的方案进入原策略 fallback。"""

    def __init__(
        self, *, config_supplier: Callable[[], dict], phase_check: Callable,
        fallback_loader: Callable[[str, float], Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config_supplier = config_supplier
        self.phase_check = phase_check
        self.fallback_loader = fallback_loader
        self.logger = logger or logging.getLogger("aitc.control.safety")

    def check(self, intersection_id: str, raw_plan: Any, *, config: dict | None = None) -> PlanSafetyResult:
        """只读检查；不取整、不修正、不调用模型，缺规则返回 partial。"""
        try:
            plan = signal_plan_from_legacy(intersection_id, raw_plan)
        except (ValueError, ValidationError):
            return PlanSafetyResult(intersection_id=intersection_id, status="invalid", issues=["invalid_signal_plan_contract"])
        issues = []
        if plan.reserved != 0:
            issues.append("reserved_slot_must_be_zero")
        program = plan.program_id
        if isinstance(program, str):
            if not re.fullmatch(r"[0-9]+", program):
                issues.append("invalid_program_id")
            else:
                try:
                    program = int(program)
                except ValueError:
                    issues.append("invalid_program_id")
        elif program < 0 or program != int(program):
            issues.append("invalid_program_id")
        else:
            program = int(program)
        ended = False
        for index, duration in enumerate(plan.phase_times):
            if duration == 0:
                ended = True
            elif ended:
                issues.append(f"phase_{index}_after_zero_terminator")
        if issues:
            return PlanSafetyResult(intersection_id=intersection_id, status="invalid", plan=plan, issues=issues)
        if not any(plan.phase_times):
            if program == 0:
                return PlanSafetyResult(intersection_id=intersection_id, status="no_action", plan=plan)
            return PlanSafetyResult(intersection_id=intersection_id, status="invalid", plan=plan, issues=["empty_active_program"])

        config = self.config_supplier() if config is None else config
        if intersection_id not in config:
            return PlanSafetyResult(intersection_id=intersection_id, status="partial", plan=plan, missing_rules=["intersection_config"])
        programs = config[intersection_id]
        if not isinstance(programs, dict):
            return PlanSafetyResult(intersection_id=intersection_id, status="invalid", plan=plan, issues=["invalid_static_config"])
        rules = programs.get(str(program))
        if rules is None:
            return PlanSafetyResult(intersection_id=intersection_id, status="partial", plan=plan, missing_rules=["program_config"])
        if not isinstance(rules, dict) or not rules:
            return PlanSafetyResult(intersection_id=intersection_id, status="invalid", plan=plan, issues=["invalid_static_config"])
        for key, bounds in rules.items():
            if (not isinstance(key, str) or not re.fullmatch(r"[0-8]", key)
                    or not isinstance(bounds, (list, tuple)) or len(bounds) != 2
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or isinstance(v, float) and not math.isfinite(v) or v < 0 for v in bounds)
                    or bounds[0] > bounds[1]):
                return PlanSafetyResult(intersection_id=intersection_id, status="invalid", plan=plan, issues=["invalid_static_config"])
        missing = []
        for index, duration in enumerate(plan.phase_times):
            bounds = rules.get(str(index))
            if bounds is None:
                if duration > 0:
                    missing.append(f"phase_{index}_bounds")
            elif duration == 0 and bounds[0] > 0:
                issues.append(f"phase_{index}_required_by_config")
            elif not bounds[0] <= duration <= bounds[1]:
                issues.append(f"phase_{index}_out_of_bounds")
        return PlanSafetyResult(
            intersection_id=intersection_id, status="invalid" if issues else "partial" if missing else "valid",
            plan=plan, issues=issues, missing_rules=missing,
        )

    def finalize(self, plans: dict[str, Any], *, fallback_plans: dict[str, Any] | None = None) -> tuple[dict, dict]:
        """同一批次固定配置快照，逐路口检查；所有 fallback 重新过同一道安全门。"""
        config = copy.deepcopy(self.config_supplier())
        now = time.time()
        final, reports = {}, {}
        incomplete: dict[str, list[str]] = {}
        for road, raw_plan in plans.items():
            result, legacy_report, corrections = self._prepare(road, raw_plan, config)
            source, reason = None, None
            if result.status == "invalid":
                reason = list(result.issues)
                fallback, report, changes = self._prepare(road, (fallback_plans or {}).get(road), config)
                # 缺规则沿用已确认的兼容策略：保留旧候选并明确标记 partial。
                if fallback.status in {"valid", "partial"}:
                    result, legacy_report, corrections, source = fallback, report, changes, "baseline_candidate"
                if source is None and self.fallback_loader is not None:
                    fallback, report, changes = self._prepare(road, self.fallback_loader(road, now), config)
                    if fallback.status in {"valid", "partial"}:
                        result, legacy_report, corrections, source = fallback, report, changes, "timetable"
                if source is None:
                    # 复用旧 selector 的无动作标记；不是新造的全红或绿灯方案。
                    result = self.check(road, [0] * 10, config=config)
                    legacy_report, corrections, source = {"check_status": 2, "msg": "Unsafe plan blocked", "modifications": []}, [], "no_action"
            final[road] = signal_plan_to_legacy(result.plan)
            reports[road] = dict(legacy_report, safety_status=result.status, safe=result.safe,
                                 issues=result.issues, missing_rules=result.missing_rules,
                                 safety_modifications=corrections, fallback_source=source, fallback_reason=reason)
            if source is not None:
                self.logger.warning("Safety fallback intersection=%s source=%s reason=%s", road, source, reason)
            if result.status == "partial":
                incomplete[road] = list(result.missing_rules)
        if incomplete:
            self.logger.warning("Safety coverage incomplete intersections=%s", incomplete)
        return final, reports

    def _prepare(self, road: str, raw_plan: Any, config: dict):
        original = self.check(road, raw_plan, config=config)
        # 只有单纯越界才允许沿用旧 phase_check 的确定性边界修正。
        correctable = original.status != "invalid" or all(issue.endswith("_out_of_bounds") for issue in original.issues)
        if not correctable:
            return original, {"check_status": 2, "msg": "Invalid signal plan", "modifications": []}, []
        checked, report = self.phase_check({road: signal_plan_to_legacy(original.plan)}, config_snapshot=config)
        result = self.check(road, checked.get(road), config=config)
        return result, report[road], report[road]["modifications"]
