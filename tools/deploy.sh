#!/bin/bash
# AITC 一键部署（内网离线）
# 用法: sudo bash tools/deploy.sh /path/to/AITC-V3.0.xxxx.x.zip
# 可用环境变量覆盖: AITC_BASE / AITC_PYTHON / AITC_HTTP_PORT
set -euo pipefail

ZIP="${1:-}"
BASE="${AITC_BASE:-/home/user/Serve_AITC/TLServer}"
PYTHON="${AITC_PYTHON:-python3}"
HTTP_PORT="${AITC_HTTP_PORT:-8088}"

usage() {
  echo "用法: bash tools/deploy.sh <AITC-V*.zip>"
  echo "  可选: AITC_BASE=/home/user/Serve_AITC/TLServer AITC_PYTHON=python3 AITC_HTTP_PORT=8088"
  exit 2
}

[[ -n "$ZIP" ]] || usage
[[ -f "$ZIP" ]] || { echo "[失败] 找不到安装包: $ZIP"; exit 2; }
ZIP="$(cd "$(dirname "$ZIP")" && pwd)/$(basename "$ZIP")"
PKG="$(basename "$ZIP" .zip)"
TARGET="$BASE/$PKG"

echo "== 1/6 校验安装包 =="
if [[ -f "$ZIP.sha256" ]]; then
  (cd "$(dirname "$ZIP")" && sha256sum -c "$(basename "$ZIP").sha256")
else
  echo "  [提示] 未找到 .sha256，跳过校验"
fi

echo "== 2/6 解压到 $TARGET =="
mkdir -p "$BASE"
[[ -e "$TARGET" ]] && { echo "[失败] 目标目录已存在: $TARGET"; exit 1; }
if command -v unzip >/dev/null 2>&1; then
  unzip -q "$ZIP" -d "$BASE"
else
  "$PYTHON" -m zipfile -e "$ZIP" "$BASE"
fi
[[ -f "$TARGET/Server_AITC.py" ]] || { echo "[失败] 解压后缺少 Server_AITC.py"; exit 1; }

echo "== 3/6 安装离线依赖 =="
cd "$TARGET"
if [[ -d offline_wheels ]]; then
  if ! "$PYTHON" -m pip install --no-index --find-links offline_wheels -r offline_wheels/requirements.txt; then
    echo "  [重试] 使用 --break-system-packages"
    "$PYTHON" -m pip install --break-system-packages --no-index --find-links offline_wheels -r offline_wheels/requirements.txt
  fi
  "$PYTHON" -m pip check || echo "  [警告] pip check 报告冲突，请人工确认"
else
  echo "  [警告] 包内没有 offline_wheels，跳过依赖安装"
fi

echo "== 4/6 停止旧服务 =="
OLD_PIDS="$(pgrep -f 'Server_AITC.py' || true)"
if [[ -n "$OLD_PIDS" ]]; then
  echo "  停止 PID: $(echo "$OLD_PIDS" | tr '\n' ' ')"
  kill $OLD_PIDS 2>/dev/null || true
  for _ in $(seq 1 10); do
    pgrep -f 'Server_AITC.py' >/dev/null 2>&1 || break
    sleep 1
  done
  if pgrep -f 'Server_AITC.py' >/dev/null 2>&1; then
    echo "  强制结束"
    pkill -9 -f 'Server_AITC.py' || true
    sleep 1
  fi
else
  echo "  没有正在运行的旧服务"
fi

echo "== 5/6 启动新服务 =="
nohup "$PYTHON" Server_AITC.py > AITC.log 2>&1 &
NEW_PID=$!
echo "  PID: $NEW_PID，日志: $TARGET/AITC.log"

echo "== 6/6 健康检查 http://127.0.0.1:$HTTP_PORT/health =="
ok=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$HTTP_PORT/health" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 1
done

if [[ "$ok" == "1" ]]; then
  echo "[成功] 新版本已启动"
  curl -s "http://127.0.0.1:$HTTP_PORT/health" | head -c 300
  echo
  echo "  回滚方法: 停掉当前进程，进入旧版本目录执行 nohup $PYTHON Server_AITC.py > AITC.log 2>&1 &"
  exit 0
fi

echo "[失败] 健康检查超时，最后 40 行日志："
tail -40 AITC.log
exit 1
