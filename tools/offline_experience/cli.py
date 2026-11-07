#!/usr/bin/env python3
"""离线经验表工具（骨架）。

契约见同目录 README.md：训练 → 补气 → 校验 → （可选）发布。
当前只实现参数解析、输入检查与 ``--dry-run``；训练/补气/发布由离线学习负责人补齐。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# 本文件位于 tools/offline_experience/，把仓库根目录加入 sys.path
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NO_DATA = 3


def _parse_dates(raw: str) -> list[date]:
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if not items:
        raise ValueError("--dates 不能为空")
    parsed = []
    for item in items:
        try:
            parsed.append(date.fromisoformat(item))
        except ValueError as error:
            raise ValueError(f"非法日期 {item!r}，要求 YYYY-MM-DD") from error
    return sorted(set(parsed))


def _parse_roads(raw: str) -> list[str]:
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if not items:
        raise ValueError("--roads 不能为空")
    invalid = [item for item in items if not item.isdigit()]
    if invalid:
        raise ValueError(f"路口 ID 必须为数字：{invalid}")
    return list(dict.fromkeys(items))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="offline_experience",
        description="离线经验表：训练 → 补气 → 校验 → 发布（骨架）",
    )
    parser.add_argument("--dates", required=True, help="训练源日期，逗号分隔 YYYY-MM-DD")
    parser.add_argument("--roads", required=True, help="训练路口 ID，逗号分隔")
    parser.add_argument("--flow-dir", default="logs_data/flow", help="流量日志目录")
    parser.add_argument("--extend-dir", default="logs_data/extend", help="阶段日志目录")
    parser.add_argument("--cross-info", default="lib/cross_info.json", help="路口渠化/相位配置")
    parser.add_argument(
        "--output",
        default="logs_data/training_results/offline_candidate.json",
        help="候选经验表输出路径",
    )
    parser.add_argument("--report", default=None, help="运行报告路径（默认 <output>.report.json）")
    parser.add_argument("--no-fill", action="store_true", help="跳过补气（buqi）步骤")
    parser.add_argument(
        "--runtime-table",
        default="lib/offline_experience.json",
        help="--activate 时的发布目标",
    )
    parser.add_argument("--versions-dir", default="lib/experience_versions", help="版本目录")
    parser.add_argument("--manifest", default=None, help="激活清单路径（默认 <versions-dir>/active_manifest.json）")
    parser.add_argument("--dry-run", action="store_true", help="只解析输入并输出计划，不写文件")
    parser.add_argument("--activate", action="store_true", help="校验通过后发布到 --runtime-table")
    return parser


def resolve_plan(args: argparse.Namespace) -> dict:
    """把命令行参数解析成可执行计划；不读日志内容，只做存在性检查。"""
    dates = _parse_dates(args.dates)
    roads = _parse_roads(args.roads)

    flow_dir = Path(args.flow_dir)
    extend_dir = Path(args.extend_dir)
    cross_info = Path(args.cross_info)
    output = Path(args.output)
    report = Path(args.report) if args.report else output.with_suffix(".report.json")
    versions_dir = Path(args.versions_dir)
    manifest = Path(args.manifest) if args.manifest else versions_dir / "active_manifest.json"

    missing: list[str] = []
    sources: dict[str, dict[str, str]] = {}
    for source_date in dates:
        day = source_date.isoformat()
        flow = flow_dir / f"{day}_flow.txt"
        extend = extend_dir / f"{day}_extend.txt"
        sources[day] = {"flow": str(flow), "extend": str(extend)}
        if not flow.is_file():
            missing.append(str(flow))
        if not extend.is_file():
            missing.append(str(extend))
    if not cross_info.is_file():
        missing.append(str(cross_info))

    return {
        "action": "offline_experience_training",
        "dry_run": bool(args.dry_run),
        "activate": bool(args.activate),
        "fill": not args.no_fill,
        "dates": [item.isoformat() for item in dates],
        "roads": roads,
        "sources": sources,
        "cross_info": str(cross_info),
        "output": str(output),
        "report": str(report),
        "runtime_table": str(Path(args.runtime_table)),
        "versions_dir": str(versions_dir),
        "manifest": str(manifest),
        "missing_inputs": missing,
    }


def run_pipeline(plan: dict) -> dict:
    """执行训练 → 补气 → 校验 → 发布。

    待实现（离线学习负责人）：复用
    ``lib/data_ANS/E_T_new.py``、``lib/data_ANS/buqi_new2.0.py``、
    ``lib/data_ANS/experience_release.py``，不要重写算法。
    """
    raise NotImplementedError("离线训练管线尚未实现（骨架），见 tools/offline_experience/README.md")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        plan = resolve_plan(args)
    except ValueError as error:
        print(f"参数错误：{error}", file=sys.stderr)
        return EXIT_USAGE

    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return EXIT_NO_DATA if plan["missing_inputs"] else EXIT_OK

    try:
        run_pipeline(plan)
    except NotImplementedError as error:
        print(str(error), file=sys.stderr)
        return EXIT_ERROR
    except Exception as error:  # noqa: BLE001 - 骨架阶段统一转成退出码
        print(f"运行失败：{type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
