# Architecture

## Goal

Hermes is the orchestration layer above agent CLIs.

It should own:
- task intake
- routing
- context injection
- stage execution
- retries and fallbacks
- structured artifacts
- run auditability

It should not depend on unstable stdout formatting from any one provider.

## Core Components

### 1. Task Intake

Accept one normalized task object:
- task id
- intent
- goal
- cwd
- constraints
- context files
- optional policy overrides

### 2. Router

Turn a task into a pipeline decision.

Example rules:
- simple implementation -> `codex`
- large refactor -> `claude -> codex -> claude`
- code review -> `claude`
- exploratory repo inspection -> `claude planner -> codex executor`

### 3. Context Injector

Build a shared prompt context from:
- durable memory
- project-local docs
- task-specific context files
- run-local stage artifacts

### 4. Stage Runner

Each stage must receive:
- the task object
- prior stage artifacts
- explicit output schema
- explicit artifact path

Each stage must return:
- one JSON artifact file
- optional stdout and stderr captures

### 5. Artifact Store

Every run should keep:
- prompts
- invocation metadata
- stdout and stderr
- stage result JSON
- one run summary JSON

This is required for replay, debugging, and operator trust.

### 6. Policy Layer

Policies should stay outside provider-specific code.

Important policies:
- route selection
- retry count
- provider fallback
- timeout budget
- filesystem boundaries
- approval/sandbox mode

## Recommended First-Class Pipelines

### Fast Implement

`codex`

Use when:
- the task is local and concrete
- code edits are bounded
- deep review is not required up front

### Standard Change

`claude -> codex -> claude`

Use when:
- the task touches multiple files
- you want plan, implementation, and review separation
- correctness matters more than raw speed

### Review Only

`claude`

Use when:
- the code already changed
- the operator wants risk analysis and findings

## WSL2-First Principle

For long-term stability:
- keep the repo in the Linux filesystem
- run provider CLIs from WSL2 where possible
- treat Windows paths as compatibility inputs, not the default operating mode

Hermes should eventually normalize paths at the boundary so a task can declare either Windows or Linux-style paths and still be routed correctly.
