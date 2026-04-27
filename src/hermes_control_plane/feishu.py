from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _nested_get(data: dict[str, Any], path: list[str], default: Any = None) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


@dataclass(slots=True)
class FeishuNotifier:
    url: str
    secret: str | None
    message_prefix: str
    notify_on: set[str]

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "FeishuNotifier | None":
        feishu_cfg = config.get("feishu", {})
        if not feishu_cfg or not feishu_cfg.get("enabled", False):
            return None

        mode = feishu_cfg.get("mode", "webhook")
        if mode == "app":
            # App mode: notifications are sent by server.py's FeishuAppSender.
            # FeishuNotifier (webhook-based) is not used in app mode.
            return None
        if mode != "webhook":
            raise RuntimeError(f"Unsupported Feishu mode: {mode}")

        webhook_cfg = feishu_cfg.get("webhook", {})
        url_env = webhook_cfg.get("url_env", "FEISHU_WEBHOOK_URL")
        secret_env = webhook_cfg.get("secret_env", "FEISHU_WEBHOOK_SECRET")
        url = os.environ.get(url_env, "").strip()
        secret = os.environ.get(secret_env, "").strip() or None
        if not url:
            raise RuntimeError(
                f"Feishu webhook is enabled but environment variable '{url_env}' is not set."
            )

        notify_on = _nested_get(config, ["feishu", "events", "notify_on"], default=None)
        if notify_on is None:
            notify_on = feishu_cfg.get(
                "notify_on",
                ["run_started", "run_completed", "run_failed", "review_needs_work"],
            )

        return cls(
            url=url,
            secret=secret,
            message_prefix=webhook_cfg.get("message_prefix", "[Hermes]").strip() or "[Hermes]",
            notify_on=set(notify_on),
        )

    def _signed_envelope(self, text: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "msg_type": "text",
            "content": {"text": text},
        }
        if not self.secret:
            return payload

        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{self.secret}"
        sign = base64.b64encode(
            hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        ).decode("utf-8")
        payload["timestamp"] = timestamp
        payload["sign"] = sign
        return payload

    def send_text(self, event: str, text: str) -> dict[str, Any]:
        if event not in self.notify_on:
            return {"event": event, "skipped": True, "reason": "event-disabled"}

        payload = self._signed_envelope(text)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response_text = response.read().decode("utf-8", errors="replace")
                return {
                    "event": event,
                    "ok": 200 <= response.status < 300,
                    "status": response.status,
                    "response_text": response_text,
                }
        except urllib.error.HTTPError as exc:
            return {
                "event": event,
                "ok": False,
                "status": exc.code,
                "response_text": exc.read().decode("utf-8", errors="replace"),
            }
        except Exception as exc:  # pragma: no cover
            return {"event": event, "ok": False, "error": str(exc)}


def render_run_message(
    event: str,
    task_id: str,
    goal: str,
    run_dir: Path,
    pipeline: str,
    profile: str,
    summary: str | None = None,
    extra_lines: list[str] | None = None,
    prefix: str = "[Hermes]",
) -> str:
    title_map = {
        "run_started": "run started",
        "run_completed": "run completed",
        "run_failed": "run failed",
        "review_needs_work": "review needs work",
    }
    lines = [
        f"{prefix} {title_map.get(event, event)}",
        f"task: {task_id}",
        f"pipeline: {pipeline}",
        f"profile: {profile}",
        f"run_dir: {run_dir}",
        f"goal: {goal}",
    ]
    if summary:
        lines.append(f"summary: {summary}")
    if extra_lines:
        lines.extend(extra_lines)
    return "\n".join(lines)
