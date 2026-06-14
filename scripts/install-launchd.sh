#!/bin/bash
# 安裝並載入 launchd 常駐服務（backend:8000、frontend:5173，KeepAlive 自動重啟）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS" "$ROOT/logs"

echo "==> 清除佔用 8000 / 5173 的舊程序..."
for PORT in 8000 5173; do
  PIDS=$(lsof -ti tcp:$PORT || true)
  if [ -n "$PIDS" ]; then
    kill $PIDS 2>/dev/null || true
    sleep 1
    PIDS=$(lsof -ti tcp:$PORT || true)
    [ -n "$PIDS" ] && kill -9 $PIDS 2>/dev/null || true
  fi
done

for NAME in com.yuanta.trading.backend com.yuanta.trading.frontend; do
  PLIST="$AGENTS/$NAME.plist"
  echo "==> 安裝 $NAME"
  # 若已載入，先卸載舊版
  launchctl bootout "gui/$(id -u)/$NAME" 2>/dev/null || true
  cp "$ROOT/scripts/launchd/$NAME.plist" "$PLIST"
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  launchctl kickstart "gui/$(id -u)/$NAME" || true
done

echo "==> 已載入。狀態："
launchctl list | grep com.yuanta.trading || true
echo "驗證：curl http://127.0.0.1:8000/api/health ; curl http://127.0.0.1:5173/"
