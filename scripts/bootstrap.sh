#!/bin/bash
# Safe first-run bootstrap: install dependencies, create local env files, and
# optionally start the localhost-only dev services.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

START=0
if [ "${1:-}" = "--start" ]; then
  START=1
elif [ "${1:-}" != "" ]; then
  echo "Usage: scripts/bootstrap.sh [--start]" >&2
  exit 2
fi

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

need_cmd python3.11
need_cmd node
need_cmd npm
need_cmd curl

echo "==> Python: $(python3.11 --version)"
echo "==> Node: $(node --version)"
echo "==> npm: $(npm --version)"
echo "==> Machine: $(uname -sm)"

echo "==> Preparing backend virtualenv"
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  python3.11 -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements.txt"

echo "==> Preparing project-local .NET 8 runtime"
if [ ! -x "$ROOT/.dotnet/dotnet" ]; then
  curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 8.0 --runtime dotnet --install-dir "$ROOT/.dotnet"
fi

echo "==> Installing frontend packages"
npm --prefix "$ROOT/frontend" install

echo "==> Preparing local env files"
if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
fi
if [ ! -f "$ROOT/frontend/.env" ]; then
  cp "$ROOT/frontend/.env.example" "$ROOT/frontend/.env"
fi

API_KEY_VALUE="$("$ROOT/.venv/bin/python" - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"

"$ROOT/.venv/bin/python" - "$ROOT/.env" "$ROOT/frontend/.env" "$API_KEY_VALUE" <<'PY'
from pathlib import Path
import sys

backend_path = Path(sys.argv[1])
frontend_path = Path(sys.argv[2])
generated = sys.argv[3]


def read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def upsert(lines: list[str], key: str, value: str) -> list[str]:
    prefix = key + "="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            current = line.split("=", 1)[1].strip()
            if current:
                return lines
            lines[index] = prefix + value
            return lines
    lines.append(prefix + value)
    return lines


backend_lines = read_lines(backend_path)
frontend_lines = read_lines(frontend_path)

existing = ""
for line in backend_lines:
    if line.startswith("API_KEY="):
        existing = line.split("=", 1)[1].strip()
        break
api_key = existing or generated

backend_lines = upsert(backend_lines, "API_KEY", api_key)
frontend_lines = upsert(frontend_lines, "VITE_API_KEY", api_key)

backend_path.write_text("\n".join(backend_lines).rstrip() + "\n", encoding="utf-8")
frontend_path.write_text("\n".join(frontend_lines).rstrip() + "\n", encoding="utf-8")
PY

echo "==> Local env ready: .env and frontend/.env"
echo "    Safety defaults remain UAT / YUANTA_ENABLE_ORDER=NO unless you edit them."

if [ "$START" -eq 1 ]; then
  echo "==> Starting localhost dev services"
  "$ROOT/scripts/dev.sh"
  echo "==> Open http://127.0.0.1:5173"
else
  echo "==> Install complete. Start with: scripts/dev.sh"
fi
