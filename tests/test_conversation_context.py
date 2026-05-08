from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hermes_control_plane import conversation, server
from hermes_control_plane import mobile_commands


class ConversationContextTests(unittest.TestCase):
    def setUp(self) -> None:
        conversation.reset_store()
        mobile_commands.reset_pending_store()

    def tearDown(self) -> None:
        conversation.reset_store()
        mobile_commands.reset_pending_store()

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
        self.assertEqual(server._strip_command_prefix("/status taac"), ("status", "taac"))
        self.assertEqual(server._strip_command_prefix("/handoff"), ("handoff", ""))
        self.assertEqual(server._strip_command_prefix("/tail hermes"), ("tail", "hermes"))
        self.assertEqual(server._strip_command_prefix("/approve approve-12345678"), ("approve", "approve-12345678"))
        self.assertEqual(server._strip_command_prefix("普通问题"), (None, "普通问题"))

    def test_high_risk_action_creates_pending_action(self) -> None:
        sent: list[str] = []

        with mock.patch.object(server, "_send_feishu_text", side_effect=lambda _s, _t, msg: sent.append(msg)):
            with mock.patch.object(server, "_run_pipeline_async") as run_pipeline:
                server._dispatch_feishu_text(
                    Path("/tmp/hermes.local.toml"),
                    {},
                    "/task 提交 TAAC 平台训练 r1-008",
                    None,
                    None,
                    "session-1",
                )

        run_pipeline.assert_not_called()
        self.assertEqual(len(mobile_commands.get_pending_store().list_for_session("session-1")), 1)
        self.assertIn("/approve approve-", sent[0])
        self.assertIn("platform training submission", sent[0])

    def test_approve_releases_pending_action(self) -> None:
        action = mobile_commands.get_pending_store().create(
            "session-1",
            "/task 提交 TAAC 平台训练 r1-008",
            "platform training submission",
        )
        sent: list[str] = []

        with mock.patch.object(server, "_send_feishu_text", side_effect=lambda _s, _t, msg: sent.append(msg)):
            with mock.patch.object(server, "_run_pipeline_async") as run_pipeline:
                with mock.patch.object(
                    server,
                    "_build_task_from_text",
                    return_value=({"goal": "提交 TAAC 平台训练 r1-008"}, "default"),
                ):
                    server._dispatch_feishu_text(
                        Path("/tmp/hermes.local.toml"),
                        {},
                        f"/approve {action.action_id}",
                        None,
                        None,
                        "session-1",
                    )
                    for _ in range(20):
                        if run_pipeline.called:
                            break
                        time.sleep(0.01)

        self.assertTrue(any("已批准" in msg for msg in sent))
        run_pipeline.assert_called_once()

    def test_wrong_session_cannot_approve_action(self) -> None:
        action = mobile_commands.get_pending_store().create(
            "session-1",
            "git push origin main",
            "GitHub write action",
        )
        sent: list[str] = []

        with mock.patch.object(server, "_send_feishu_text", side_effect=lambda _s, _t, msg: sent.append(msg)):
            with mock.patch.object(server, "_run_pipeline_async") as run_pipeline:
                server._dispatch_feishu_text(
                    Path("/tmp/hermes.local.toml"),
                    {},
                    f"/approve {action.action_id}",
                    None,
                    None,
                    "session-2",
                )

        run_pipeline.assert_not_called()
        self.assertIn("没有找到", sent[0])

    def test_status_command_returns_project_status(self) -> None:
        sent: list[str] = []

        with mock.patch.object(server, "_send_feishu_text", side_effect=lambda _s, _t, msg: sent.append(msg)):
            server._dispatch_feishu_text(
                Path("/tmp/hermes.local.toml"),
                {},
                "/status taac",
                None,
                None,
                "session-1",
            )

        self.assertIn("leaderboard AUC", sent[0])


if __name__ == "__main__":
    unittest.main()
