from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_control_plane import conversation, server


class ConversationContextTests(unittest.TestCase):
    def setUp(self) -> None:
        conversation.reset_store()

    def tearDown(self) -> None:
        conversation.reset_store()

    def test_default_store_keeps_sessions_for_a_day(self) -> None:
        store = conversation.get_store()

        session = store.get_or_create("session-1")

        self.assertEqual(session.max_age, conversation.DEFAULT_MAX_AGE_SECONDS)

    def test_pipeline_result_is_saved_back_to_conversation(self) -> None:
        store = conversation.get_store()
        task = {"goal": "为什么，你自己修复一下"}

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            summary_path = run_dir / "run_summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "stages": [
                            {
                                "stage": "executor",
                                "artifact": {"summary": "GitHub API 访问失败，仓库列表不完整"},
                            },
                            {
                                "stage": "reviewer",
                                "artifact": {
                                    "verdict": "needs-work",
                                    "summary": "需要补上用户可见的中文回复",
                                    "findings": [
                                        {
                                            "severity": "high",
                                            "issue": "任务结果没有回写到会话上下文",
                                        }
                                    ],
                                },
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with mock.patch("hermes_control_plane.runner.run_pipeline", return_value=run_dir):
                server._run_pipeline_async(
                    Path("/tmp/hermes.local.toml"),
                    task,
                    "fast_implement",
                    None,
                    None,
                    session_id="session-1",
                )

        history = store.get_history("session-1", n=10)

        self.assertEqual([item["role"] for item in history], ["user", "assistant"])
        self.assertEqual(history[0]["content"], task["goal"])
        self.assertIn("GitHub API 访问失败", history[1]["content"])
        self.assertIn("审核结论：needs-work", history[1]["content"])

    def test_follow_up_task_includes_recent_conversation_context(self) -> None:
        store = conversation.get_store()
        store.add_message("session-1", "user", "那你现在可以打开我的github吗？看看，里面有哪些内容，哪些是我上传的")
        store.add_message(
            "session-1",
            "assistant",
            "✅ 任务完成！\n\n📋 执行结果：GitHub API 访问失败，仓库列表不完整",
        )

        with mock.patch.object(server, "_codex_config_path", return_value="/tmp/missing-config.toml"):
            with mock.patch.object(server, "_codex_auth_path", return_value="/tmp/missing-auth.json"):
                task, _pipeline = server._build_task_from_text("为什么，你自己修复一下", session_id="session-1")

        notes_text = "\n".join(task["notes"])

        self.assertIn("Recent conversation context:", notes_text)
        self.assertIn("打开我的github", notes_text)
        self.assertIn("GitHub API 访问失败", notes_text)

    def test_mobile_command_prefixes_are_parsed(self) -> None:
        self.assertEqual(server._strip_command_prefix("/chat 你好"), ("chat", "你好"))
        self.assertEqual(server._strip_command_prefix("/fast 修一下"), ("fast", "修一下"))
        self.assertEqual(server._strip_command_prefix("/task 帮我跑测试"), ("task", "帮我跑测试"))
        self.assertEqual(server._strip_command_prefix("/review 看一下"), ("review", "看一下"))
        self.assertEqual(server._strip_command_prefix("普通问题"), (None, "普通问题"))


if __name__ == "__main__":
    unittest.main()
