# Hermes Control Plane

Route real coding tasks across Codex CLI and Claude Code through a Feishu bot.

## Portfolio Snapshot

Hermes is a mobile-first AI control plane for practical software workflows. It demonstrates multi-agent orchestration, intent-based routing, Feishu WebSocket integration, and local-first automation for coding tasks that need more than a single chat window.

- Portfolio angle: multi-agent workflow systems and operator-facing AI tooling
- Core evidence: explicit pipeline modes, WSL2-first execution, Feishu control surface, config templates, architecture docs, route tests, and run artifacts
- Case study: [docs/CASE_STUDY.md](docs/CASE_STUDY.md)
- Routing policy: [docs/ROUTING_POLICY.md](docs/ROUTING_POLICY.md)

## Why It Matters

Most agent demos stop at "one model, one task, one terminal." Real team workflows are messier:

- some requests need planning before execution
- some should skip planning and go straight to implementation
- some are review-only and should never touch files
- some need human approval checkpoints and external messaging

Hermes is a control plane for that layer.

## What To Notice

This repository is meant to show more than a chatbot wrapper:

- `src/hermes_control_plane/router.py` separates routing policy from execution.
- `src/hermes_control_plane/runner.py` writes per-stage artifacts and run summaries.
- `src/hermes_control_plane/server.py` supports Feishu intake, including WebSocket mode to avoid public tunnels.
- `config/hermes.local.example.toml` documents local profiles for Windows, WSL2, and mixed execution.
- `tests/test_router.py` gives the routing layer regression coverage, including Chinese mobile instructions.

## What Hermes Does

- Accepts tasks through Feishu over WebSocket, without requiring a public tunnel
- Classifies intent and routes requests into different execution pipelines
- Supports planner-executor-reviewer workflows across multiple coding agents
- Keeps the runtime local-first, with WSL2-friendly execution and lightweight Python dependencies
- Exposes a structure that can later be extended to Slack, Discord, browser agents, or internal ops tools

## Pipeline Modes

### Default

`Claude -> Codex -> Claude`

Use for feature work, complex tasks, and requests that benefit from planning plus review.

### Fast Implement

`Codex only`

Use for bug fixes, focused code changes, and low-ceremony implementation tasks.

### Review Only

`Claude only`

Use for audits, code review, and read-only investigation.

### Smoke

`Claude -> Claude -> Claude`

Use for health checks, environment checks, and end-to-end pipeline verification.

## Technical Highlights

- Python 3.11+
- standard-library-first implementation
- Feishu WebSocket integration
- WSL2-aware path and process handling
- MCP-friendly Codex execution model
- deterministic routing tests for review, fix, small implementation, and default flows

## Quick Start

```bash
git clone https://github.com/benben951/hermes-control-plane.git
cd hermes-control-plane
pip install -e .
cp config/hermes.local.example.toml config/hermes.local.toml
```

Then configure your Feishu app credentials and local agent commands before running:

```bash
hermes serve --config config/hermes.local.toml --port 8765 --mode websocket
```

## Verify Locally

```bash
python -m pytest -q
```

## Project Structure

```text
config/                      config templates and route definitions
docs/                        architecture and case-study docs
examples/                    sample task templates
src/hermes_control_plane/    server, runner, router, contracts, integrations
tests/                       regression coverage
```

## Resume Angle

Built a mobile-first multi-agent control plane that routes real coding tasks across Codex CLI and Claude Code through Feishu, with intent-based pipeline selection, WSL2-first local execution, and operator-friendly workflow control.

## Interview Talking Points

- Why routing matters: real AI coding work needs different workflows for implementation, review, status checks, and small fixes.
- Why local-first: mobile control is useful, but credentials and local repositories should not require a public tunnel by default.
- Why artifacts matter: planner, executor, and reviewer stages need structured outputs so failures can be replayed and audited.
- What I would improve next: add route confidence, approval gates for destructive tasks, artifact schema validation, and run-level metrics.
