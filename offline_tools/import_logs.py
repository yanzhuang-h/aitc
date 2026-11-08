#!/usr/bin/env python3
"""AITC 离线日志数据导入与标准化工具 (Log Importer).

用于将外部导出的原始 flow (流量) 与 extend (信控) 数据文件安全导入并标准化归档至
logs_data/ 目录下，供离线训练模块自动读取。

完全独立，零外部依赖，仅基于 Python 原生标准库。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from pathlib import Path
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple

LOGGER = logging.getLogger("LogImporter")

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_LOGS_DIR = TOOLS_DIR / "logs_data"

DATE_PATTERN = re.compile(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})")


def extract_date_from_string(text: str) -> Optional[str]:
    """从文件名或字符串中提取 YYYY-MM-DD 标准日期格式。"""
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    year, month, day = match.groups()
    try:
        parsed = dt.date(int(year), int(month), int(day))
        return parsed.isoformat()
    except ValueError:
        return None


def inspect_file_head(file_path: Path, max_lines: int = 5) -> Tuple[bool, Optional[str], Optional[str]]:
    """检测文件前几行 JSON，推断属于 flow 还是 extend，以及格式是否合法。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            valid_json_count = 0
            inferred_kind = None
            sample_date = None
            for _ in range(max_lines):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    valid_json_count += 1
                    # 推断数据类型
                    if "jtll_ddbh" in obj or "ycsb_cdbh" in obj:
                        inferred_kind = "flow"
                    elif "CrossId" in obj and "curStageNo" in obj:
                        inferred_kind = "extend"

                    # 尝试从时间戳提取日期
                    ts = obj.get("time") or obj.get("ts")
                    if ts and isinstance(ts, (int, float, str)):
                        try:
                            ts_int = int(ts)
                            if ts_int > 10_000_000_000:
                                ts_int //= 1000
                            if ts_int > 0:
                                sample_date = dt.datetime.fromtimestamp(ts_int).strftime("%Y-%m-%d")
                        except (ValueError, OSError):
                            pass
                except json.JSONDecodeError:
                    pass

            return valid_json_count > 0, inferred_kind, sample_date
    except Exception as exc:
        LOGGER.warning("无法读取文件 %s: %s", file_path, exc)
        return False, None, None


def import_single_file(
    src_file: Path,
    kind: str,
    date_str: str,
    target_logs_dir: Path,
    mode: str = "copy",
) -> Path:
    """导入单个日志文件到标准目标目录。"""
    dest_dir = target_logs_dir / kind
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{date_str}_{kind}.txt"

    if mode == "symlink":
        if dest_file.exists() or dest_file.is_symlink():
            dest_file.unlink()
        dest_file.symlink_to(src_file.resolve())
    elif mode == "move":
        shutil.move(str(src_file), str(dest_file))
    else:  # copy
        shutil.copy2(str(src_file), str(dest_file))

    return dest_file


def scan_and_import_dir(
    src_dir: Path,
    target_logs_dir: Path,
    mode: str = "copy",
) -> Dict[str, Dict[str, str]]:
    """扫描源目录并自动分类导入所有识别到的 flow/extend 文件。"""
    imported: Dict[str, Dict[str, str]] = {}

    for file_path in src_dir.rglob("*"):
        if not file_path.is_file() or file_path.name.startswith("."):
            continue

        lower_name = file_path.name.lower()
        # 1. 判断种类
        kind = None
        if "flow" in lower_name:
            kind = "flow"
        elif "extend" in lower_name or "signal" in lower_name or "stage" in lower_name:
            kind = "extend"

        # 2. 提取日期
        date_str = extract_date_from_string(file_path.name)

        # 3. 若文件名无法确定，通过文件内容探测
        valid_json, content_kind, sample_date = inspect_file_head(file_path)
        if not valid_json:
            continue
        if not kind:
            kind = content_kind
        if not date_str:
            date_str = sample_date

        if not kind or not date_str:
            LOGGER.debug("跳过无法确定日期或种类的文件: %s", file_path)
            continue

        dest_file = import_single_file(file_path, kind, date_str, target_logs_dir, mode=mode)
        if date_str not in imported:
            imported[date_str] = {}
        imported[date_str][kind] = str(dest_file)
        LOGGER.info("已导入: %s -> %s (%s)", file_path.name, dest_file, mode)

    return imported


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AITC 离线日志数据导入与标准化工具 (Log Importer)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--src",
        help="待扫描导入的原始日志文件所在目录（将自动递归扫描并识别 flow/extend）",
    )
    parser.add_argument(
        "--flow",
        help="显式指定单个 flow 日志文件路径",
    )
    parser.add_argument(
        "--extend",
        help="显式指定单个 extend 日志文件路径",
    )
    parser.add_argument(
        "--date",
        help="指定日期（格式 YYYY-MM-DD）。在使用 --flow/--extend 时有效；未指定时自动从文件名推断",
    )
    parser.add_argument(
        "--dest",
        default=str(DEFAULT_LOGS_DIR),
        help="目标 logs_data 根目录路径",
    )
    parser.add_argument(
        "--mode",
        choices=["copy", "move", "symlink"],
        default="copy",
        help="导入方式: copy(复制文件), move(移动文件), symlink(建立软链接节省磁盘空间)",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    )

    dest_dir = Path(args.dest).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    imported_summary: Dict[str, Dict[str, str]] = {}

    # 方式一：指定源目录批量自动识别扫描
    if args.src:
        src_path = Path(args.src).resolve()
        if not src_path.is_dir():
            LOGGER.error("源目录不存在或不是目录: %s", src_path)
            return 1
        LOGGER.info("开始扫描源目录: %s", src_path)
        imported_summary = scan_and_import_dir(src_path, dest_dir, mode=args.mode)

    # 方式二：显式指定单日文件
    elif args.flow or args.extend:
        if args.flow:
            flow_path = Path(args.flow).resolve()
            date_str = args.date or extract_date_from_string(flow_path.name)
            if not date_str:
                LOGGER.error("无法推断 flow 文件对应日期，请使用 --date YYYY-MM-DD 显式指定")
                return 1
            out = import_single_file(flow_path, "flow", date_str, dest_dir, mode=args.mode)
            imported_summary.setdefault(date_str, {})["flow"] = str(out)

        if args.extend:
            extend_path = Path(args.extend).resolve()
            date_str = args.date or extract_date_from_string(extend_path.name)
            if not date_str:
                LOGGER.error("无法推断 extend 文件对应日期，请使用 --date YYYY-MM-DD 显式指定")
                return 1
            out = import_single_file(extend_path, "extend", date_str, dest_dir, mode=args.mode)
            imported_summary.setdefault(date_str, {})["extend"] = str(out)
    else:
        parser.print_help()
        LOGGER.error("请指定 --src 目录，或者指定 --flow / --extend 文件")
        return 1

    print("\n" + "=" * 60)
    print(f"日志导入完成！目标目录: {dest_dir}")
    print(f"共导入 {len(imported_summary)} 个日期的日志数据:")
    complete_count = 0
    for date_str, files in sorted(imported_summary.items()):
        has_flow = "flow" in files
        has_extend = "extend" in files
        is_complete = has_flow and has_extend
        if is_complete:
            complete_count += 1
        status = "【完整可用】" if is_complete else "【仅部分文件】"
        print(f"  - {date_str}: {status} flow={has_flow}, extend={has_extend}")
    print(f"\n成对完整可用天数: {complete_count} / {len(imported_summary)}")
    print("=" * 60 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
