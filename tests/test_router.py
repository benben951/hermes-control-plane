from __future__ import annotations

from hermes_control_plane.contracts import TaskSpec
from hermes_control_plane.router import choose_pipeline


def test_review_intents_route_to_review_only() -> None:
    assert choose_pipeline({"intent": "review", "goal": "review this PR"}) == "review_only"
    assert choose_pipeline({"intent": "audit", "goal": "audit the routing policy"}) == "review_only"


def test_fix_intent_routes_to_fast_implement() -> None:
    assert choose_pipeline({"intent": "fix", "goal": "repair the failing import"}) == "fast_implement"


def test_small_english_implementation_routes_to_fast_implement() -> None:
    task = TaskSpec(
        id="small-doc-edit",
        intent="implement",
        goal="Make a small change in a single file",
        cwd=".",
    )

    assert choose_pipeline(task) == "fast_implement"


def test_small_chinese_implementation_routes_to_fast_implement() -> None:
    task = {
        "intent": "implement",
        "goal": "只改一个单文件，做一个简单修改",
    }

    assert choose_pipeline(task) == "fast_implement"


def test_complex_implementation_uses_default_pipeline() -> None:
    task = {
        "intent": "implement",
        "goal": "refactor the server, runner, and Feishu integration with review",
    }

    assert choose_pipeline(task) == "default"
