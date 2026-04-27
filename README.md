# Hermes Control Plane

> A WSL2-first orchestration layer that routes tasks across **OpenAI Codex CLI** and **Anthropic Claude Code** via **Feishu (Lark) Bot** — with zero Python dependencies beyond stdlib.

## What It Does

Hermes sits between your Feishu chat and your coding agents. Send a message in Feishu, Hermes figures out what you want, picks the right pipeline, and runs it:

```
Feishu Message
    │
    ▼
┌─────────────────────────┐
│  LLM Classifier (GPT)   │  ← intent + type in one API call
│  chat / task / review    │
└─────────┬───────────────┘
          │
    ┌─────┴─────┐
    │           │
 chat         task
    │           │
    ▼           ▼
 GPT-4o     Router
 quick       choose_pipeline()
 reply       │
             ├── default ──────── Claude (plan) → Codex (exec) → Claude (review)
             ├── fast_implement ─ Codex (exec)
             ├── review_only ──── Claude (review)
             └── smoke ────────── Claude → Claude → Claude (health check)
                              │
                              ▼
                      Results → Feishu
```

## Key Features

- **WebSocket Mode** — Direct connection to Feishu cloud, no public tunnel needed
- **Smart Routing** — LLM classifies intent (implement/fix/review/audit/research/verify) and picks the optimal pipeline
- **Multi-Agent Pipelines** — Chain Claude (planning) → Codex (execution) → Claude (code review)
- **Fast Path** — Single-step Codex for bug fixes and small changes (skip planning/review)
- **Zero Python Dependencies** — Only stdlib (`http.server`, `json`, `hashlib`, etc.)
- **MCP Support** — Codex executor can use MCP tools (Playwright, filesystem, fetch, GitHub, etc.)
- **Watchdog** — Auto-restarts on crash with rate limiting
- **Windows + WSL2** — Runs inside WSL2, auto-starts via Windows Startup folder

## Architecture

| Module | Responsibility |
|---|---|
| `server.py` | Feishu WebSocket client, message handler, LLM classifier, pipeline trigger |
| `runner.py` | Pipeline executor — runs planner/executor/reviewer stages sequentially |
| `router.py` | Intent-based pipeline selection (`choose_pipeline()`) |
| `contracts.py` | Data classes: `TaskSpec`, `StageResult`, `Finding`, `RunSummary` |
| `feishu.py` | Feishu API client (send messages, notifications) |

## Prerequisites

- **Python 3.11+** (no pip packages required)
- **OpenAI Codex CLI** (`npm install -g @openai/codex`)
- **Anthropic Claude Code** (`npm install -g @anthropic-ai/claude-code`)
- **Feishu App** (create one at [open.feishu.cn](https://open.feishu.cn))
- **WSL2** (Ubuntu recommended)

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/benben951/hermes-control-plane.git
cd hermes-control-plane
pip install -e .
```

### 2. Configure

Copy the example config and fill in your values:

```bash
cp config/hermes.local.example.toml config/hermes.local.toml
```

Edit `config/hermes.local.toml`:

```toml
[hermes]
default_profile = "wsl_mixed"
runs_root = "/home/<YOUR_USERNAME>/.hermes/runs"
shared_context_files = ["/home/<YOUR_USERNAME>/.hermes/context.md"]

[feishu]
mode = "app"
enabled = true

[feishu.app]
app_id = "your_feishu_app_id"
app_secret = "your_feishu_app_secret"
message_prefix = "[Hermes]"

# Configure Codex CLI paths for your environment
[profiles.wsl_mixed.codex]
enabled = true
command = ["codex", "exec", "--skip-git-repo-check", "-"]

[profiles.wsl_mixed.claude]
enabled = true
command = ["/mnt/c/Users/<YOUR_USERNAME>/.local/bin/claude.exe", "--bare", "-p", "--output-format", "json", "--permission-mode", "acceptEdits"]
run_cwd = "/mnt/c/Users/<YOUR_USERNAME>"
```

### 3. Create shared context file (optional)

```bash
mkdir -p ~/.hermes
echo "# Project Context\n\nAdd your project context here. This gets injected into every task." > ~/.hermes/context.md
```

### 4. Run

```bash
hermes serve --config config/hermes.local.toml --port 8765 --mode websocket
```

Or use the launcher script:

```bash
python launch_hermes.py start
```

## Pipelines

### Default Pipeline (full orchestration)

For feature development and complex tasks:

```
Claude (planner) → Codex (executor) → Claude (reviewer)
```

Claude analyzes the request, creates a plan. Codex implements it. Claude reviews the code.

### Fast Implement Pipeline

For bug fixes and single-file changes:

```
Codex (executor)
```

Skip planning and review. Go straight to implementation.

### Review Only Pipeline

For code audits and reviews:

```
Claude (reviewer)
```

Only code review, no modifications.

### Smoke Pipeline

Health check / connectivity test:

```
Claude → Claude → Claude
```

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CODEX_CONFIG_PATH` | `~/.codex/config.toml` | Path to Codex CLI config |
| `CODEX_AUTH_PATH` | `~/.codex/auth.json` | Path to Codex CLI auth |
| `HERMES_CONTEXT_PATH` | `~/.hermes/context.md` | Path to shared context file |

### Feishu App Setup

1. Go to [open.feishu.cn](https://open.feishu.cn) → Create App
2. Enable **Bot** capability
3. Enable **WebSocket** mode (Events → Message Received)
4. Add permissions: `im:message`, `im:message:send_as_bot`
5. Copy `App ID` and `App Secret` into your config

## Auto-Start (Windows)

### Startup Folder

Place the launcher script in Windows Startup folder:

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\start_hermes_silent.bat
```

Content:

```bat
@echo off
start "" /min wsl.exe -e bash -lc "nohup bash ~/hermes_watchdog.sh > /dev/null 2>&1 & cd /path/to/hermes-control-plane && python3 launch_hermes.py start"
```

### Watchdog

The watchdog (`hermes_watchdog.sh`) monitors Hermes every 30 seconds and auto-restarts it on crash:

- Rate limited: max 10 restarts per hour
- Logs to `/tmp/hermes_watchdog.log`

## MCP Tools for Codex

Configure MCP servers in `~/.codex/config.toml`:

```toml
[mcp_servers.playwright]
command = "npx"
args = ["@playwright/mcp@latest"]

[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]

[mcp_servers.fetch]
command = "uvx"
args = ["mcp-server-fetch"]
```

This gives Codex access to browser automation, file system, and web fetching during execution.

## Project Structure

```text
hermes-control-plane/
├── config/
│   ├── hermes.local.example.toml    # Config template
│   ├── feishu.example.toml          # Feishu config template
│   ├── agents.example.toml          # Agent profiles
│   └── routes.example.json          # Route rules
├── docs/
│   ├── ARCHITECTURE.md              # Architecture deep-dive
│   ├── FEISHU.md                    # Feishu integration guide
│   ├── OPERATIONS.md                # Operations manual
│   └── WSL2_FIRST.md               # WSL2 setup notes
├── src/hermes_control_plane/
│   ├── __main__.py                  # CLI entry point
│   ├── server.py                    # Feishu WebSocket + message handler
│   ├── runner.py                    # Pipeline executor
│   ├── router.py                    # Intent-based pipeline selector
│   ├── contracts.py                 # Data classes
│   └── feishu.py                    # Feishu API client
├── examples/
│   ├── smoke.task.json              # Health check task
│   └── task.template.json           # Task template
├── scripts/
│   ├── install_wsl2.sh              # WSL2 setup
│   ├── doctor.sh                    # Dependency checker
│   └── run_hermes.sh               # Run script
└── tests/
```

## How It Works

### Message Flow

1. **Feishu sends a WebSocket event** when a user messages the bot
2. **LLM Classifier** (GPT-4o-mini) analyzes the message in one API call:
   - `msg_type`: `chat` (quick Q&A) or `task` (needs agent)
   - `intent`: `implement`, `fix`, `review`, `audit`, `research`, `verify`
3. **Router** picks pipeline based on intent:
   - `fix` / small `implement` → `fast_implement`
   - `review` / `audit` → `review_only`
   - large `implement` → `default`
4. **Runner** executes the pipeline stages sequentially
5. **Results** are sent back to Feishu

### Why Not Use a Framework?

Hermes uses zero Python dependencies by design. The orchestration logic is straightforward — HTTP serving, subprocess management, and JSON parsing. This makes it:
- Easy to debug (no framework magic)
- Lightweight (fast startup, low memory)
- Portable (works anywhere Python 3.11+ is available)

## Contributing

PRs welcome! Areas where contributions are especially helpful:

- **New pipelines** — add your own pipeline configs in `config/`
- **LLM classifier improvements** — better intent recognition prompts
- **New integrations** — Slack, Discord, WeChat, etc.
- **Error handling** — better retry/fallback strategies

## License

MIT

## Author

[benben951](https://github.com/benben951)
