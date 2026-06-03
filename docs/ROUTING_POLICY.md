# Routing Policy

Hermes treats routing as a first-class engineering decision instead of hiding every request behind one agent command.

The goal is not to prove that one model is always better. The goal is to choose the smallest reliable workflow for the operator's intent.

## Pipeline Decision Table

| User intent | Example request | Pipeline | Why |
| --- | --- | --- | --- |
| `fix` | "repair the failing import" | `fast_implement` | A bounded fix usually does not need a planner/reviewer round trip. |
| `implement` + small scope | "make a small change in a single file" | `fast_implement` | Low ceremony keeps latency down. |
| `implement` + broad scope | "refactor server, runner, and Feishu integration" | `default` | Planner, executor, and reviewer separation reduces regression risk. |
| `review` / `audit` | "review this PR" | `review_only` | Read-only work should not trigger file edits. |

## Current Rule Set

`src/hermes_control_plane/router.py` implements a compact deterministic router:

- review-like intents route to `review_only`
- fix intents route to `fast_implement`
- implementation requests mentioning small scope route to `fast_implement`
- everything else routes to `default`

The router intentionally supports both English and Chinese small-scope phrases, because the operator may send mobile instructions in either language.

## Safety Boundaries

Routing policy is separated from the runner so future policies can be added without rewriting provider-specific execution code.

Current boundaries:

- review-only tasks skip implementation stages
- stage outputs use explicit JSON contracts
- run artifacts are written per task for auditability
- secrets are expected in local config or environment variables, not in git

## Next Practical Extensions

The next version should add:

- confidence scores for borderline routing decisions
- explicit "needs approval" route for destructive operations
- retry and fallback policy per stage
- artifact validation before the reviewer stage
- route-level metrics such as latency, failure rate, and manual override frequency
