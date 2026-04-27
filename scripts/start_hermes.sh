#!/usr/bin/env bash
# start_hermes.sh — 一键启动 Hermes HTTP Server + Cloudflare Tunnel
# Usage: bash scripts/start_hermes.sh [--port 8765]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG="${PROJECT_DIR}/config/hermes.local.toml"
PORT="${HERMES_PORT:-8765}"
CLOUDFLARED="${HOME}/.local/bin/cloudflared"

# Parse --port flag
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# Activate venv
source "${PROJECT_DIR}/.venv/bin/activate"

echo "=============================================="
echo "  Hermes Control Plane — Starting up"
echo "  Config : $CONFIG"
echo "  Port   : $PORT"
echo "=============================================="

# Start Hermes HTTP server in background
python -m hermes_control_plane serve \
  --config "$CONFIG" \
  --port "$PORT" &
HERMES_PID=$!

# Wait for server to be ready
echo "[*] Waiting for Hermes to start..."
for i in $(seq 1 20); do
  if curl -sf "http://127.0.0.1:${PORT}/health" > /dev/null 2>&1; then
    echo "[*] Hermes is up!"
    break
  fi
  sleep 0.5
done

# Start cloudflared tunnel
echo "[*] Starting Cloudflare Tunnel on port ${PORT}..."
"$CLOUDFLARED" tunnel --url "http://127.0.0.1:${PORT}" --no-autoupdate 2>&1 | \
  tee /tmp/cloudflared.log &
CF_PID=$!

# Wait for tunnel URL
echo "[*] Waiting for tunnel URL..."
TUNNEL_URL=""
for i in $(seq 1 40); do
  TUNNEL_URL=$(grep -oP 'https://[a-z0-9\-]+\.trycloudflare\.com' /tmp/cloudflared.log 2>/dev/null | head -1 || true)
  if [[ -n "$TUNNEL_URL" ]]; then
    break
  fi
  sleep 1
done

echo ""
echo "=============================================="
if [[ -n "$TUNNEL_URL" ]]; then
  echo "  ✅ Tunnel URL: $TUNNEL_URL"
  echo ""
  echo "  ⬇️  复制这个 URL 到飞书应用后台："
  echo "  飞书开放平台 → 你的应用 → 事件与回调 → 事件配置"
  echo "  请求网址(Request URL): ${TUNNEL_URL}/feishu/event"
  echo "  (飞书验证时 Hermes 会自动响应 challenge)"
else
  echo "  ⚠️  Tunnel URL not detected yet, check /tmp/cloudflared.log"
fi
echo "=============================================="
echo ""
echo "  Hermes PID: $HERMES_PID"
echo "  Cloudflared PID: $CF_PID"
echo ""
echo "  Press Ctrl+C to stop both services."
echo ""

# Keep running and handle Ctrl+C
trap "echo 'Stopping...'; kill $HERMES_PID $CF_PID 2>/dev/null; exit 0" INT TERM
wait $HERMES_PID
