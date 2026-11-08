"""独立离线训练模块 - 命令行入口 (CLI).

完全独立，零外部依赖，仅基于 Python 标准库。
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
from pathlib import Path
import sys
from typing import Optional, Sequence

from .pipeline import resolve_date_list, run_offline_pipeline

LOGGER = logging.getLogger("OfflineTrainer")

DEFAULT_MODULE_DIR = Path(__file__).resolve().parent

# 定位独立根目录（优先 tools/，完全自包含）
DEFAULT_ROOT_DIR = (
    DEFAULT_MODULE_DIR.parent
    if DEFAULT_MODULE_DIR.parent.name == "tools"
    else DEFAULT_MODULE_DIR.parent / "tools"
    if (DEFAULT_MODULE_DIR.parent / "tools").is_dir()
    else DEFAULT_MODULE_DIR.parent
)

DEFAULT_LOGS_DIR_PATH = Path(
    os.environ.get("AITC_LOGS_DIR", str(DEFAULT_ROOT_DIR / "logs_data"))
).resolve()
# 独立路口配置位于 offline_trainer 外部 (tools/configs/cross_info.json)，便于单独替换与后续核心代码加密
DEFAULT_CROSS_INFO_PATH = DEFAULT_ROOT_DIR / "configs" / "cross_info.json"
DEFAULT_TARGET_TABLE_PATH = (
    DEFAULT_ROOT_DIR / "experience_pool" / "offline_experience.json"
)


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="AITC 100% 独立离线学习 / 经验表冷启动训练模块",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--roads",
        required=True,
        help="目标训练路口 ID 列表，以逗号分隔，如 1300069,1300068,1300067,1700125",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="训练天数（从昨日往前倒推连续 N 天）。当未指定 --dates 时生效",
    )
    parser.add_argument(
        "--dates",
        help="显式指定训练日期（优先级高于 --days）。支持逗号分隔如 2026-07-01,2026-07-02 或区间如 2026-07-01:2026-07-14",
    )
    parser.add_argument(
        "--logs-dir",
        default=str(DEFAULT_LOGS_DIR_PATH),
        help="流量 (flow) 与阶段放行 (extend) 独立日志根目录",
    )
    parser.add_argument(
        "--cross-info",
        default=str(DEFAULT_CROSS_INFO_PATH),
        help="路口静态配置文件路径（位于 tools/configs/cross_info.json，便于独立替换与维护）",
    )
    parser.add_argument(
        "--target-table",
        default=str(DEFAULT_TARGET_TABLE_PATH),
        help="离线经验底表路径（合并写入目标）",
    )
    parser.add_argument(
        "--output-dir",
        help="离线训练结果与质检报告输出目录。默认在 logs_data/offline_training/<时间戳>",
    )
    parser.add_argument(
        "--merge",
        "--merge-to-online",
        dest="merge_to_online",
        action="store_true",
        default=True,
        help="是否将训练结果无损合并写入底表 (默认开启自动合并)",
    )
    parser.add_argument(
        "--no-merge",
        dest="merge_to_online",
        action="store_false",
        help="仅生成单次分析报告与临时表，不合并写入正式底表",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="合并写入底表时不创建 .bak 备份文件",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式：仅检查路口存在性及数据日志完整度，不执行实际算法训练",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="打印详细调试日志",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    )

    try:
        roads = [r.strip() for r in args.roads.split(",") if r.strip()]
        dates = resolve_date_list(
            dates_arg=args.dates,
            days_arg=args.days,
        )

        logs_dir = Path(args.logs_dir).resolve()
        cross_info_path = Path(args.cross_info).resolve()
        target_table_path = Path(args.target_table).resolve()

        if args.output_dir:
            output_dir = Path(args.output_dir).resolve()
        else:
            timestamp_tag = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = logs_dir / "offline_training" / timestamp_tag

        result = run_offline_pipeline(
            road_ids=roads,
            dates=dates,
            logs_dir=logs_dir,
            cross_info_path=cross_info_path,
            output_dir=output_dir,
            target_table_path=target_table_path,
            merge_to_online=args.merge_to_online,
            backup=not args.no_backup,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )

        print("\n" + "=" * 60)
        print("离线训练执行完毕！")
        print(f"状态: {result.get('status')}")
        if result.get("merge_result"):
            print(f"已成功合并至生产底表: {result['merge_result']['target_table']}")
            print(f"更新路口集合: {result['merge_result']['updated_roads']}")
        print(f"输出目录: {output_dir}")
        print("=" * 60 + "\n")
        return 0
    except Exception as error:
        LOGGER.exception("离线训练执行失败: %s", error)
        print(f"\n[ERROR] 训练失败: {error}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
