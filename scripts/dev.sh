#!/bin/bash
# 一次性啟動後端 (uvicorn:8000) 與前端 (vite:5173)，log 寫到 logs/
# 若已用 launchd 常駐（scripts/install-launchd.sh），請勿同時使用本腳本。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/logs"

echo "==> 清除佔用 8000 / 5173 的舊程序..."
for PORT in 8000 5173; do
  PIDS=$(lsof -ti tcp:$PORT || true)
  if [ -n "$PIDS" ]; then
    echo "    port $PORT: kill $PIDS"
    kill $PIDS 2>/dev/null || true
    sleep 1
    PIDS=$(lsof -ti tcp:$PORT || true)
    [ -n "$PIDS" ] && kill -9 $PIDS 2>/dev/null || true
  fi
done

echo "==> 啟動後端 uvicorn (127.0.0.1:8000) -> logs/uvicorn.log"
cd "$ROOT"
nohup "$ROOT/.venv/bin/python" -m uvicorn backend.app.main:app \
  --host 127.0.0.1 --port 8000 \
  >> "$ROOT/logs/uvicorn.log" 2>&1 &
echo "    backend pid: $!"

echo "==> 啟動前端 vite (127.0.0.1:5173) -> logs/vite.log"
cd "$ROOT/frontend"
nohup npm run dev >> "$ROOT/logs/vite.log" 2>&1 &
echo "    frontend pid: $!"

echo "==> 完成。檢查："
echo "    curl http://127.0.0.1:8000/api/health"
echo "    curl http://127.0.0.1:5173/"
