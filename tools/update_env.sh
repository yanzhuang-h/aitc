#!/bin/bash
# AITC 环境更新脚本（在解压后的版本目录内执行）
# 用法: bash tools/update_env.sh
# 只负责安装离线依赖；停止/启动服务由运维按自己的流程执行。
set -euo pipefail

PYTHON="${AITC_PYTHON:-python3}"
PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PKG_DIR"

echo "== 1/3 检查运行环境 =="
"$PYTHON" -V
"$PYTHON" - <<'PY'
import sys
if sys.version_info[:2] != (3, 11):
    raise SystemExit("需要 Python 3.11，当前 %s" % sys.version.split()[0])
PY

if [[ ! -d offline_wheels ]]; then
  echo "[失败] 当前目录缺少 offline_wheels/，请在解压后的版本目录执行本脚本"
  exit 1
fi

echo "== 2/3 安装离线依赖 =="
if ! "$PYTHON" -m pip install --no-index --find-links offline_wheels -r offline_wheels/requirements.txt; then
  echo "  [重试] 使用 --break-system-packages"
  "$PYTHON" -m pip install --break-system-packages --no-index --find-links offline_wheels -r offline_wheels/requirements.txt
fi
"$PYTHON" -m pip check || echo "  [警告] pip check 报告冲突，请人工确认"

echo "== 3/3 验证导入 =="
"$PYTHON" - <<'PY'
import apscheduler
import chinese_calendar
import langgraph
import mcp
import numpy
import pydantic

print("依赖导入正常")
PY

echo
echo "环境更新完成。接下来请按自己的流程操作："
echo "  1) 停止旧进程: pkill -f Server_AITC.py"
echo "  2) 启动新版本: nohup $PYTHON Server_AITC.py > AITC.log 2>&1 &"
echo "  3) 检查:       curl -s http://127.0.0.1:8088/health"
