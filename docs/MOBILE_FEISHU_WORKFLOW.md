# Mobile Feishu Workflow

Hermes can be used as a phone-first control plane through a Feishu bot. The design goal is to make quick conversations fast while still allowing long-running Codex and Claude Code tasks when the user explicitly asks for them.

## Architecture

```text
Phone / Feishu
  -> Feishu Bot WebSocket
  -> Hermes server in WSL2
  -> Message router
     -> quick chat: direct OpenAI-compatible API call
     -> fast task: Codex executor only
     -> review task: Claude reviewer only
     -> full task: Claude planner -> Codex executor -> Claude reviewer
  -> Feishu reply
```

## Command Prefixes

Use a prefix when sending messages from Feishu to avoid slow or incorrect intent classification.

| Prefix | Route | Use case |
|---|---|---|
| `/chat` | Quick chat | Q&A, summaries, translation, planning, resume wording, non-tool answers |
| `/fast` | `fast_implement` | Small code edits, config fixes, quick local checks |
| `/task` | Default pipeline | Multi-step implementation, research plus code, platform work |
| `/review` | `review_only` | Code review, experiment review, safety checks |
| `/status` | Health response | Confirm the bot is online and list supported prefixes |

Examples:

```text
/chat 帮我把今天的工作整理成简历 bullet
/fast 修一下 README 里的命令说明
/task 检查 TAAC 新实验结果并更新实验文档
/review 复核这次 Kaggle notebook 有没有数据泄漏
/status
```

## Runtime Layout

Recommended local layout:

- Hermes server: WSL2 Linux filesystem, for example `/home/<user>/workspace/hermes-control-plane`
- Hermes Python environment: project-local `.venv`
- Watchdog: WSL shell script that restarts Hermes if it crashes
- Codex: WSL-native command when possible
- Claude Code: either WSL-native command or Windows executable through `/mnt/c/...`

When Claude Code is invoked from WSL through a Windows executable path, long tasks may be slower because the call crosses the WSL/Windows boundary. Keep quick phone messages on `/chat` and reserve `/task` for work that truly needs tools.

## Performance Notes

- `/chat` avoids the full multi-agent pipeline and should be used for ordinary conversation.
- `/fast` bypasses planning and review for small implementation tasks.
- `/task` can be slow because it may run planner, executor, and reviewer stages.
- The WebSocket handler dispatches task preparation to a background thread so incoming Feishu events are not blocked by task analysis.
- Shared context files are useful but can increase latency; keep them compact and factual.

## Security Notes

- Do not commit `config/hermes.local.toml`, app secrets, API keys, cookies, Codex auth files, or historical memory files.
- Store secrets in local config files or environment variables only.
- Rotate any credential that was pasted into chat, committed, logged, or stored in old memory files.
