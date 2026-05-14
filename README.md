<p align="center">
  <h1 align="center">Hermes Control Plane</h1>
  <p align="center">
    <strong>Route tasks across OpenAI Codex CLI + Anthropic Claude Code via Feishu Bot</strong>
  </p>
  <p align="center">
    <a href="#features">Features</a> 路 <a href="#quick-start">Quick Start</a> 路 <a href="#pipelines">Pipelines</a> 路 <a href="#configuration">Configuration</a>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.11+-blue?logo=python" alt="Python 3.11+">
    <img src="https://img.shields.io/badge/Zero_Dependencies-stdlib-green" alt="Zero Dependencies">
    <img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT License">
    <img src="https://img.shields.io/badge/Feishu-WebSocket-blue" alt="Feishu WebSocket">
  </p>
</p>

<p align="center">
  <img src="docs/architecture.svg" alt="Hermes Architecture" width="900">
</p>

## 鉁?Features

## Portfolio Snapshot

Hermes is a mobile-first AI control plane for real coding workflows. It demonstrates multi-agent orchestration, LLM-based intent routing, Feishu WebSocket integration, and local-first automation for Codex CLI and Claude Code.

- Portfolio angle: practical AI agent orchestration and workflow automation.
- Core evidence: pipeline modes, WSL2-first design, Feishu bot control, config templates, architecture docs, and regression tests.
- More details: [Case Study](docs/CASE_STUDY.md)

- **WebSocket Mode** 鈥?Direct connection to Feishu cloud, no public tunnel (no ngrok/cloudflared)
- **Smart Routing** 鈥?GPT-4o-mini classifies intent in one API call, picks the optimal pipeline
- **4 Pipeline Modes** 鈥?Full orchestration, fast implement, review-only, or smoke test
- **Zero Python Dependencies** 鈥?Only stdlib (`http.server`, `json`, `hashlib`, etc.)
- **MCP Support** 鈥?Codex executor can use Playwright, filesystem, fetch, GitHub tools
- **Auto-Start** 鈥?Windows Startup folder + watchdog with crash recovery
- **WSL2-First** 鈥?Designed for WSL2 with Windows cross-filesystem support

## 馃殌 Quick Start

### Prerequisites

- **Python 3.11+** (no pip packages needed)
- **OpenAI Codex CLI** 鈥?`npm install -g @openai/codex`
- **Anthropic Claude Code** 鈥?`npm install -g @anthropic-ai/claude-code`
- **Feishu App** 鈥?Create at [open.feishu.cn](https://open.feishu.cn)
- **WSL2** (Ubuntu recommended, but not required)

### 1. Install

```bash
git clone https://github.com/benben951/hermes-control-plane.git
cd hermes-control-plane
pip install -e .
```

### 2. Configure

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

[profiles.wsl_mixed.codex]
enabled = true
command = ["codex", "exec", "--skip-git-repo-check", "-"]

[profiles.wsl_mixed.claude]
enabled = true
command = ["/mnt/c/Users/<YOUR_USERNAME>/.local/bin/claude.exe", "--bare", "-p", "--output-format", "json", "--permission-mode", "acceptEdits"]
run_cwd = "/mnt/c/Users/<YOUR_USERNAME>"
```

### 3. Run

```bash
hermes serve --config config/hermes.local.toml --port 8765 --mode websocket
```

## 馃攧 Pipelines

### Default Pipeline (Full Orchestration)

For feature development and complex tasks:

```
Claude (planner) 鈫?Codex (executor) 鈫?Claude (reviewer)
```

### Fast Implement Pipeline

For bug fixes and single-file changes:

```
Codex (executor)  鈫?skip planning & review
```

### Review Only Pipeline

For code audits and reviews:

```
Claude (reviewer)  鈫?read-only, no modifications
```

### Smoke Pipeline

Health check / connectivity test:

```
Claude 鈫?Claude 鈫?Claude
```

## 鈿欙笍 Configuration

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CODEX_CONFIG_PATH` | `~/.codex/config.toml` | Codex CLI config file |
| `CODEX_AUTH_PATH` | `~/.codex/auth.json` | Codex CLI auth credentials |
| `HERMES_CONTEXT_PATH` | `~/.hermes/context.md` | Shared context file injected into tasks |

### Feishu App Setup

1. Go to [open.feishu.cn](https://open.feishu.cn) 鈫?Create App
2. Enable **Bot** capability
3. Enable **WebSocket** mode (Events 鈫?Message Received)
4. Add permissions: `im:message`, `im:message:send_as_bot`
5. Copy `App ID` and `App Secret` into your config

### MCP Tools for Codex

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

## 馃悤 Auto-Start (Windows)

### Startup Folder

Place in Windows Startup folder:

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\start_hermes_silent.bat
```

```bat
@echo off
start "" /min wsl.exe -e bash -lc "nohup bash ~/hermes_watchdog.sh > /dev/null 2>&1 & cd /path/to/hermes-control-plane && python3 launch_hermes.py start"
```

### Watchdog

The watchdog monitors Hermes every 30 seconds:

- Auto-restarts on crash
- Rate limited: max 10 restarts per hour
- Logs to `/tmp/hermes_watchdog.log`

## 馃搧 Project Structure

```text
hermes-control-plane/
鈹溾攢鈹€ config/
鈹?  鈹溾攢鈹€ hermes.local.example.toml    # Config template
鈹?  鈹溾攢鈹€ feishu.example.toml          # Feishu config template
鈹?  鈹溾攢鈹€ agents.example.toml          # Agent profiles
鈹?  鈹斺攢鈹€ routes.example.json          # Route rules
鈹溾攢鈹€ docs/
鈹?  鈹溾攢鈹€ architecture.svg             # Architecture diagram
鈹?  鈹溾攢鈹€ ARCHITECTURE.md              # Architecture deep-dive
鈹?  鈹溾攢鈹€ FEISHU.md                    # Feishu integration guide
鈹?  鈹斺攢鈹€ WSL2_FIRST.md               # WSL2 setup notes
鈹溾攢鈹€ src/hermes_control_plane/
鈹?  鈹溾攢鈹€ server.py                    # Feishu WebSocket + message handler
鈹?  鈹溾攢鈹€ runner.py                    # Pipeline executor
鈹?  鈹溾攢鈹€ router.py                    # Intent-based pipeline selector
鈹?  鈹溾攢鈹€ contracts.py                 # Data classes (TaskSpec, etc.)
鈹?  鈹斺攢鈹€ feishu.py                    # Feishu API client
鈹溾攢鈹€ examples/                        # Task templates
鈹斺攢鈹€ tests/
```

## 馃 How It Works

1. **User sends a message** in Feishu 鈫?WebSocket delivers to Hermes
2. **LLM Classifier** (GPT-4o-mini) analyzes in one API call:
   - `msg_type`: `chat` (quick Q&A) or `task` (needs agent execution)
   - `intent`: `implement`, `fix`, `review`, `audit`, `research`, `verify`
3. **Router** picks pipeline based on intent:
   - `fix` / small `implement` 鈫?`fast_implement` (Codex only)
   - `review` / `audit` 鈫?`review_only` (Claude only)
   - large `implement` 鈫?`default` (full pipeline)
4. **Runner** executes pipeline stages sequentially
5. **Results** sent back to Feishu

## 馃 Contributing

PRs welcome! Especially:

- **New pipelines** 鈥?define your own in `config/`
- **New integrations** 鈥?Slack, Discord, WeChat, etc.
- **Classifier improvements** 鈥?better intent recognition

## 馃搫 License

MIT 漏 [benben951](https://github.com/benben951)
