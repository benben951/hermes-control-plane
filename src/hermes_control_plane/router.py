from __future__ import annotations

from typing import Any


def choose_pipeline(task: dict[str, Any] | Any) -> str:
    """Return a pipeline choice based on task intent and goal.

    Accepts either a TaskSpec dataclass or a plain dict with at least
    an ``intent`` and ``goal`` key (matching contracts.TaskSpec fields).
    """
    if hasattr(task, "intent"):
        intent = task.intent.lower() if isinstance(task.intent, str) else ""
        goal = task.goal.lower() if isinstance(task.goal, str) else ""
    else:
        task_dict = dict(task) if not isinstance(task, dict) else task
        intent = str(task_dict.get("intent", "")).lower()
        goal = str(task_dict.get("goal", "")).lower()

    # Review-only: skip implementation entirely
    if intent in {"review", "audit"}:
        return "review_only"

    # Fast implement: single-file or trivial edits → just executor, no planner/reviewer
    if intent in {"fix"}:
        return "fast_implement"
    if intent == "implement" and any(
        phrase in goal for phrase in (
            "single file", "small change", "minimal edit",
            "单文件", "小改动", "简单修改",
        )
    ):
        return "fast_implement"

    # Default: full 3-stage pipeline
    return "default"
