#!/usr/bin/env python3
"""AITC 离线学习快捷启动入口 (完全独立自包含).

完全使用 tools/ 内部自包含的 offline_trainer 模块、独立 configs 与独立 logs_data。
零外部依赖，不向上依赖任何项目外部目录。
"""

from __future__ import annotations

from pathlib import Path
import sys

TOOLS_DIR = Path(__file__).resolve().parent

# 仅加载 tools 内部自包含的模块
if str(TOOLS_DIR) in sys.path:
    sys.path.remove(str(TOOLS_DIR))
sys.path.insert(0, str(TOOLS_DIR))

from offline_trainer.cli import main

if __name__ == "__main__":
    sys.exit(main())
