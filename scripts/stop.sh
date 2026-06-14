#!/bin/bash
# 停用並卸載 launchd 常駐服務，並清掉殘留的 port 佔用
set -uo pipefail

AGENTS="$HOME/Library/LaunchAgents"

for NAME in com.yuanta.trading.backend com.yuanta.trading.frontend; do
  echo "==> 卸載 $NAME"
  launchctl bootout "gui/$(id -u)/$NAME" 2>/dev/null || true
  rm -f "$AGENTS/$NAME.plist"
done

for PORT in 8000 5173; do
  PIDS=$(lsof -ti tcp:$PORT || true)
  if [ -n "$PIDS" ]; then
    echo "==> 清除 port $PORT 殘留程序: $PIDS"
    kill $PIDS 2>/dev/null || true
    sleep 1
    PIDS=$(lsof -ti tcp:$PORT || true)
    [ -n "$PIDS" ] && kill -9 $PIDS 2>/dev/null || true
  fi
done

echo "==> 已停止。"
