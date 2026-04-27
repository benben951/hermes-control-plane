#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -d .venv ]]; then
  source .venv/bin/activate
fi

CONFIG_PATH="${HERMES_CONFIG:-$ROOT_DIR/config/hermes.local.toml}"
if [[ ! -f "$CONFIG_PATH" ]]; then
  CONFIG_PATH="$ROOT_DIR/config/hermes.local.example.toml"
fi

if [[ $# -eq 0 ]]; then
  set -- doctor
fi

needs_config=true
for arg in "$@"; do
  if [[ "$arg" == "--config" ]]; then
    needs_config=false
    break
  fi
done

if $needs_config; then
  exec python -m hermes_control_plane "$@" --config "$CONFIG_PATH"
else
  exec python -m hermes_control_plane "$@"
fi
