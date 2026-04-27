# Feishu Integration

## Decide The Scope First

There are two very different integration levels:

### Level 1: Outbound Notifications

Hermes sends messages into Feishu, for example:
- task started
- task completed
- task failed
- review found risks

This is the fastest useful integration.

Recommended first implementation:
- use a Feishu custom bot webhook
- send plain text or message card summaries
- keep it one-way at first

### Level 2: Inbound Control

Feishu users send a command and Hermes starts or inspects runs.

This is much more involved.

It requires:
- a Feishu app, not just a group webhook
- bot capability
- event subscriptions
- a Hermes HTTP endpoint
- signature verification and access control

Do not start here unless you specifically need "operate Hermes from inside Feishu".

## Recommended Path

Start with Level 1.

That gives you real value quickly without dragging Hermes into a full chatbot/server architecture.

## Level 1: Outbound Notification Flow

1. In a Feishu group, add a custom bot.
2. Copy the webhook URL.
3. Optionally enable keyword or signature verification.
4. Save the webhook in Hermes config or environment variables.
5. Hermes posts run summaries after each run.

Current repo status:
- webhook notifications are now implemented in the local runner
- Hermes can emit `run_started`, `run_completed`, `run_failed`, and `review_needs_work`
- the easiest setup is to enable Feishu in `config/hermes.local.toml` and export the webhook environment variables

Typical events:
- `run_started`
- `run_completed`
- `run_failed`
- `review_needs_work`

## Level 2: Inbound Control Flow

If you later want Feishu to trigger Hermes:

1. Create a Feishu app.
2. Enable the bot capability.
3. Configure event subscriptions.
4. Expose a webhook endpoint from Hermes.
5. Verify Feishu signatures.
6. Map messages or slash-style commands into Hermes task objects.
7. Return status updates through normal Feishu messages.

## Suggested Command Model

If inbound control is added later, keep the syntax narrow:

```text
/hermes run <task-template> <freeform goal>
/hermes status <run-id>
/hermes retry <run-id>
```

Avoid arbitrary shell execution from Feishu messages.

## Security Notes

- Never hardcode webhook URLs or app secrets into git.
- Prefer environment variables or ignored local config files.
- Limit who can trigger Hermes from Feishu.
- Keep destructive actions behind an approval policy even if Feishu can start tasks.

## Official References

- Feishu custom bot guide:
  `https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot?lang=zh-CN`
- Feishu send message API:
  `https://open.feishu.cn/document/server-docs/im-v1/message/create?lang=zh-CN`

Based on those docs, the pragmatic rollout is:
- first use a group custom bot webhook for notifications
- only later add a Feishu app for inbound commands

## Quick Start

1. Copy `config/hermes.local.example.toml` to `config/hermes.local.toml` if you have not already.
2. Set:
   - `feishu.enabled = true`
3. Export:

```bash
export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/..."
export FEISHU_WEBHOOK_SECRET="your-secret-if-signing-is-enabled"
```

4. Run:

```bash
bash ./scripts/run_hermes.sh doctor
bash ./scripts/run_hermes.sh pipeline --task ./examples/smoke.task.json
```

5. Check:
- terminal output
- `run_summary.json`
- `notifications/` under the run directory
