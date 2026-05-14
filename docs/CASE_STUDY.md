# Case Study: Mobile AI Workbench For Long-Running Coding Projects

Hermes Control Plane was built to make AI coding agents usable from a phone while preserving a structured engineering workflow.

## Problem

Long-running coding and competition projects often require quick checks, approvals, status updates, reviews, and small code tasks while away from the main workstation. Direct shell access from mobile is fragile, and exposing a public tunnel for a local agent stack creates unnecessary risk.

## Solution

Hermes connects a Feishu bot to local agent executors through WebSocket mode. Messages are classified into lightweight chat or executable tasks, then routed to the right pipeline.

Core routes:

| Mode | Purpose |
| --- | --- |
| `chat` | Fast Q&A without starting a full task pipeline. |
| `task` | Implementation or research task through the coding executor. |
| `review` | Read-only review flow. |
| `fast` | Small, direct Codex-only implementation path. |
| `status` | Health and run-state checks. |

## Architecture

The system is intentionally simple:

1. Feishu WebSocket receives a message.
2. A classifier maps it to chat/task/review/status.
3. The router selects a pipeline.
4. The runner invokes Codex CLI, Claude Code, or a configured local command.
5. Results are posted back to Feishu.

The project is WSL2-first and keeps secrets in local config files that are excluded from the repository.

## Engineering Choices

- Use WebSocket mode instead of public tunnels.
- Keep runtime dependencies minimal.
- Treat Codex as executor and Claude as planner/reviewer when both are available.
- Make pipeline modes explicit instead of hiding behavior behind one command.
- Add regression tests for conversation context and routing behavior.

## Portfolio Value

This project demonstrates:

- multi-agent workflow design;
- LLM-based intent routing;
- local-first automation;
- mobile control of coding workflows;
- pragmatic safety boundaries around credentials and local execution.

It is a practical AI application project rather than a toy chatbot: the system exists to control real development workflows, competition monitoring, and project reviews.
