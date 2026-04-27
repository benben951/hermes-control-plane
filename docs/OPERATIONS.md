# Operations

## What "opening Hermes" means

Hermes is not a desktop app yet.

Opening Hermes means:
- open a terminal
- `cd` into the Hermes control-plane repo
- run the Hermes CLI entrypoint

## Recommended Runtime

Use WSL2 as the primary runtime.

Recommended target repo path:

`/home/jie13/workspace/hermes-control-plane`

## First Migration From Windows

From WSL2:

```bash
mkdir -p ~/workspace
cp -r /mnt/c/Users/jie13/workspace/hermes-control-plane ~/workspace/
```

If you also want to migrate the current Windows bootstrap controller files:

```bash
cp -r /mnt/c/Users/jie13/hermes ~/workspace/hermes-bootstrap
```

## Recommended WSL2 Setup

Inside WSL2, install:
- Python 3.11+
- Node.js and npm
- git
- Codex CLI
- Claude Code CLI

Recommended provider install commands inside WSL2:

```bash
npm install -g @openai/codex
curl -fsSL https://claude.ai/install.sh | bash
```

Then verify:

```bash
python3 --version
node --version
npm --version
codex --version
claude --version
```

## Install Hermes In WSL2

Inside the repo:

```bash
cd ~/workspace/hermes-control-plane
bash ./scripts/install_wsl2.sh
```

That will:
- create `.venv`
- install the local package in editable mode
- create `config/hermes.local.toml` if it does not exist

## How Hermes Should Be Run

Normal operator commands:

```bash
cd ~/workspace/hermes-control-plane
bash ./scripts/run_hermes.sh doctor
bash ./scripts/run_hermes.sh pipeline --task ./examples/smoke.task.json
```

If native Linux Claude installation is blocked but Windows Claude Code is already installed, use the mixed profile:

```bash
bash ./scripts/run_hermes.sh doctor --profile wsl_mixed
bash ./scripts/run_hermes.sh pipeline --profile wsl_mixed --task ./examples/smoke.task.json
```

That profile expects Windows Claude Code at:

`/mnt/c/Users/jie13/.local/bin/claude.exe`

If you only want to verify that the Hermes chain works end-to-end before debugging Codex executor behavior, use the dedicated smoke pipeline:

```bash
bash ./scripts/run_hermes.sh pipeline --profile wsl_mixed --pipeline smoke --task ./examples/smoke.task.json
```

That keeps the smoke test simple by routing planner, executor, and reviewer through Claude.

Direct package entrypoint is also available after install:

```bash
source .venv/bin/activate
hermes doctor --config ./config/hermes.local.toml
hermes pipeline --config ./config/hermes.local.toml --task ./examples/smoke.task.json
```

The older runnable Windows bootstrap launcher still exists under:

`C:\Users\jie13\hermes\run_hermes_pipeline.cmd`

## Operator Model

Normal usage should be:

1. create or choose a task JSON
2. call Hermes
3. let Hermes route the task to Codex and Claude
4. inspect the run artifacts if something fails

You should not need to manually decide each time whether to call Codex or Claude. That choice belongs in Hermes policies.

## Current Gap

The repo bootstrap contains contracts, route templates, and retry templates.

It still does not yet contain:
- the real route engine implementation
- the retry executor
- Feishu notification or inbound control handlers

Those are the next build steps.
