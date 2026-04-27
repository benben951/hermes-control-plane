# WSL2-First Plan

## Why

Native Windows CLI behavior can be inconsistent across shells, path translation, and launcher wrappers.

A WSL2-first setup gives you:
- more predictable CLI execution
- a cleaner Unix-style filesystem layout
- easier scripting
- better parity with most agent and developer tooling assumptions

## Target Shape

Recommended future repo location:

`/home/jie13/workspace/hermes-control-plane`

Recommended execution model:
- Hermes runs inside WSL2
- Codex runs inside WSL2
- Claude Code runs inside WSL2 if available, otherwise through a clearly isolated Windows bridge

## Migration Strategy

1. Keep the current Windows bootstrap working.
2. Mirror the repo into WSL2.
3. Add a WSL2 provider profile in config.
4. Switch Codex execution to WSL2 first.
5. Switch Hermes itself to WSL2 once the path and artifact model are stable.

## Path Policy

Use repo-local relative paths whenever possible.

If an incoming task carries a Windows path such as:

`C:\Users\jie13\workspace\hermes-control-plane`

Hermes should be able to normalize it into:

`/mnt/c/Users/jie13/workspace/hermes-control-plane`

That normalization should live in one boundary utility, not across the whole codebase.

## Provider Strategy

Preferred order:
- Codex in WSL2
- Claude in WSL2
- Windows bridge only when required

The control plane should know which provider profile is active, and it should record that fact in every run summary.
