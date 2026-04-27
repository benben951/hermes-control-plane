#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_command python3

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e .

if [[ ! -f config/hermes.local.toml ]]; then
  cp config/hermes.local.example.toml config/hermes.local.toml
fi

if command -v codex >/dev/null 2>&1; then
  echo "Detected codex: $(codex --version)"
else
  echo "codex CLI not found in PATH. Install it inside WSL2 before running Hermes pipelines."
fi

if command -v claude >/dev/null 2>&1; then
  echo "Detected claude: $(claude --version)"
else
  echo "claude CLI not found in PATH. Install it inside WSL2 before running Hermes pipelines."
fi

cat <<'EOF'
Hermes WSL2 install complete.

Next:
1. Edit config/hermes.local.toml if needed.
2. Verify provider CLIs:
   codex --version
   claude --version
3. Optional Feishu setup:
   export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/..."
   export FEISHU_WEBHOOK_SECRET="your-secret-if-enabled"
4. Run:
   ./scripts/run_hermes.sh doctor
   ./scripts/run_hermes.sh pipeline ./examples/smoke.task.json
EOF
