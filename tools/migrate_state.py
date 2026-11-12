"""把旧版本目录里的运行状态迁移到共享目录。

生产目录结构：
    TLSserver/
      AITC-V3.0.1112.1/
      shared/
        logs_data/
        experience_pool/
        experience_versions/

用法（建议先停旧服务）：
    python tools/migrate_state.py --from ../AITC-V3.0.1112.1 --dry-run
    python tools/migrate_state.py --from ../AITC-V3.0.1112.1 --apply

默认 shared 为当前版本目录的 ../shared。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ITEMS = (
    ("logs_data", "logs_data"),
    ("lib/experience_pool", "experience_pool"),
    ("lib/experience_versions", "experience_versions"),
)


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="迁移运行状态到共享目录")
    parser.add_argument("--from", dest="source", required=True, help="旧版本目录")
    parser.add_argument("--shared", default="../shared", help="共享目录（默认 ../shared）")
    parser.add_argument("--apply", action="store_true", help="实际复制（默认只预览）")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    shared = Path(args.shared).resolve()
    if not source.is_dir():
        raise SystemExit(f"旧版本目录不存在: {source}")

    print(f"旧版本: {source}")
    print(f"共享目录: {shared}")
    total = 0
    for relative, target_name in ITEMS:
        src = source / relative
        dst = shared / target_name
        if not src.exists():
            print(f"[skip] {relative} 不存在")
            continue
        size = _size(src)
        total += size
        print(f"[plan] {src} -> {dst}  ({size / 1024 / 1024:.1f} MB)")
        if args.apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    print(f"合计 {total / 1024 / 1024:.1f} MB")
    if not args.apply:
        print("预览完成；确认后加 --apply")
    else:
        print("迁移完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
