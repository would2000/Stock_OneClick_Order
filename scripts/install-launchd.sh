#!/bin/bash
# 安裝並載入 launchd 常駐服務（backend:8000、frontend:5173，KeepAlive 自動重啟）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS" "$ROOT/logs"
NPM_BIN="$(command -v npm)"

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

BACKEND_PLIST="$AGENTS/com.yuanta.trading.backend.plist"
FRONTEND_PLIST="$AGENTS/com.yuanta.trading.frontend.plist"

echo "==> 產生 backend launchd plist"
launchctl bootout "gui/$(id -u)/com.yuanta.trading.backend" 2>/dev/null || true
cat > "$BACKEND_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.yuanta.trading.backend</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>cd "$ROOT" &amp;&amp; exec "$ROOT/.venv/bin/python" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>$ROOT/logs/uvicorn.log</string>
    <key>StandardErrorPath</key>
    <string>$ROOT/logs/uvicorn.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF
launchctl bootstrap "gui/$(id -u)" "$BACKEND_PLIST"
launchctl kickstart "gui/$(id -u)/com.yuanta.trading.backend" || true

echo "==> 產生 frontend launchd plist"
launchctl bootout "gui/$(id -u)/com.yuanta.trading.frontend" 2>/dev/null || true
cat > "$FRONTEND_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.yuanta.trading.frontend</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-lc</string>
        <string>cd "$ROOT/frontend" &amp;&amp; exec "$NPM_BIN" run dev</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>$ROOT/logs/vite.log</string>
    <key>StandardErrorPath</key>
    <string>$ROOT/logs/vite.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF
launchctl bootstrap "gui/$(id -u)" "$FRONTEND_PLIST"
launchctl kickstart "gui/$(id -u)/com.yuanta.trading.frontend" || true

echo "==> 已載入。狀態："
launchctl list | grep com.yuanta.trading || true
echo "驗證：curl http://127.0.0.1:8000/api/health ; curl http://127.0.0.1:5173/"
