from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Intent = Literal["implement", "fix", "review", "audit", "verify", "research"]
StageName = Literal["planner", "executor", "reviewer"]


@dataclass(slots=True)
class TaskSpec:
    id: str
    intent: Intent
    goal: str
    cwd: str
    constraints: list[str] = field(default_factory=list)
    context_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Finding:
    severity: Literal["high", "medium", "low"]
    file: str
    issue: str
    recommendation: str


@dataclass(slots=True)
class StageResult:
    stage: StageName
    agent: str
    status: Literal["completed", "blocked", "partial", "failed"]
    summary: str
    changed_files: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
