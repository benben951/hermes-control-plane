# Mobile Feishu Workflow

Hermes can be used as a phone-first control plane for Codex CLI and Claude Code through a Feishu bot. The default posture is safe: status checks and reviews are easy, while expensive or destructive actions require explicit approval.

## Command Set

| Command | Purpose |
| --- | --- |
| `/chat <message>` | Quick Q&A, summaries, translation, planning, and resume wording. |
| `/fast <goal>` | Small, bounded implementation through Codex only. |
| `/task <goal>` | Standard pipeline: Claude plans, Codex executes, Claude reviews. |
| `/review <goal>` | Claude review-only path for code, experiment, and safety checks. |
| `/status taac` | Summarize the TAAC best score, active run, and prepared run from local project docs. |
| `/status kaggle` | Summarize the Nemotron SFT dataset and next LoRA smoke step. |
| `/status hermes` | Show the latest Hermes run status. |
| `/handoff` | Return a compact TAAC + Kaggle handoff for continuing work from the phone. |
| `/tail hermes` | Show recent Hermes logs with volatile access fields redacted. |
| `/approve <action_id>` | Approve one pending high-risk action from the same Feishu session. |

## Approval Gate

Hermes creates a pending action instead of executing immediately when a message appears to request:

- TAAC platform training submission;
- model publishing;
- leaderboard evaluation;
- Kaggle submission;
- GitHub write actions such as `git push` or `gh pr create`;
- destructive filesystem actions;
- secret, token, cookie, or credential access.

The bot replies with an action id:

```text
Action: approve-12345678
Risk: platform training submission
Reply /approve approve-12345678 to continue.
```

Only the same Feishu user or chat session can approve that action. Pending actions expire automatically.

## Recommended Daily Usage

Start with status:

```text
/status taac
/status kaggle
```

Ask for a safe review before spending resources:

```text
/review Check whether TAAC r1-008 is ready to submit. Do not submit it.
```

Prepare work without executing the risky final step:

```text
/task Prepare the TAAC r1-008 submission checklist and update docs if needed. Do not submit platform training.
```

If you really want to execute a gated action, approve the returned id:

```text
/approve approve-12345678
```

## Privacy Rules

- Do not paste API keys, cookies, or account passwords into Feishu.
- Keep `config/hermes.local.toml`, Codex auth files, Claude settings, browser cookies, and secret stores out of git.
- Use `/tail hermes` instead of raw log screenshots; Hermes redacts common volatile access fields.
- Prefer `/review` for platform and leaderboard decisions, then approve only after the review is acceptable.
