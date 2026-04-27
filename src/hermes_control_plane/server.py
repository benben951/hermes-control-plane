"""
Hermes HTTP server — receives Feishu app events and triggers pipelines.

Zero third-party dependencies; uses only Python stdlib (http.server, json, etc.).
"""

from __future__ import annotations

import json
import http.server
import logging
import os
import re
import tempfile
import threading
import time
import uuid
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

from .conversation import get_store as _get_conv_store

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feishu App message sender (app mode, tenant_access_token)
# ---------------------------------------------------------------------------

# ── Environment / path helpers (configurable via env vars) ───────────────
def _env_home() -> str:
    """Return the user home directory."""
    return os.path.expanduser("~")

def _codex_config_path() -> str:
    """Path to Codex CLI config.toml (override via CODEX_CONFIG_PATH)."""
    return os.environ.get("CODEX_CONFIG_PATH", os.path.join(_env_home(), ".codex", "config.toml"))

def _codex_auth_path() -> str:
    """Path to Codex CLI auth.json (override via CODEX_AUTH_PATH)."""
    return os.environ.get("CODEX_AUTH_PATH", os.path.join(_env_home(), ".codex", "auth.json"))

def _hermes_context_path() -> str:
    """Path to Hermes shared context file (override via HERMES_CONTEXT_PATH)."""
    return os.environ.get("HERMES_CONTEXT_PATH", os.path.join(_env_home(), ".hermes", "context.md"))

class FeishuAppSender:
    """Send messages back to users/chats via Feishu App."""

    TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    MSG_URL   = "https://open.feishu.cn/open-apis/im/v1/messages"

    def __init__(self, app_id: str, app_secret: str, prefix: str = "[Hermes]") -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.prefix = prefix
        self._token: str | None = None
        self._token_expire: float = 0.0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expire - 60:
            return self._token
        payload = json.dumps({"app_id": self.app_id, "app_secret": self.app_secret}).encode()
        req = urllib.request.Request(
            self.TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        if proxy:
            handler = urllib.request.ProxyHandler({"https": proxy, "http": proxy})
            opener = urllib.request.build_opener(handler)
        else:
            opener = urllib.request.build_opener()
        with opener.open(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("code", 0) != 0:
            raise RuntimeError(f"Feishu token error: {data}")
        self._token = data["tenant_access_token"]
        self._token_expire = time.time() + data.get("expire", 7200)
        return self._token

    def send_text(self, receive_id: str, id_type: str, text: str) -> dict[str, Any]:
        """id_type: open_id | chat_id | user_id | union_id"""
        token = self._get_token()
        url = f"{self.MSG_URL}?receive_id_type={id_type}"
        payload = json.dumps({
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": f"{self.prefix} {text}"}),
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        if proxy:
            handler = urllib.request.ProxyHandler({"https": proxy, "http": proxy})
            opener = urllib.request.build_opener(handler)
        else:
            opener = urllib.request.build_opener()
        try:
            with opener.open(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return {"code": exc.code, "msg": exc.read().decode("utf-8", errors="replace")}




# ---------------------------------------------------------------------------
# Feishu WebSocket Client (long connection mode) — no tunnel needed!
# ---------------------------------------------------------------------------

class FeishuWSClient:
    """Receive Feishu events via WebSocket (lark-oapi SDK).

    This eliminates the need for cloudflared tunnel and manual URL updates.
    Hermes connects outbound to Feishu, no inbound firewall/NAT issues.
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        on_message: "callable",
        log_level: str = "INFO",
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.on_message = on_message  # callback: (event_dict) -> None
        self.log_level = log_level
        self._thread = None
        self._cli = None

    def start(self, in_thread: bool = True) -> None:
        """Start the WS client. If in_thread=True, runs in a daemon thread."""
        if in_thread:
            import threading
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        else:
            self._run()

    def _run(self) -> None:
        try:
            import lark_oapi as lark
        except ImportError:
            logger.error("lark-oapi not installed. Run: pip install lark-oapi")
            return

        def _do_message_receive_v1(data):
            """Handler for im.message.receive_v1 event."""
            # data is a P2ImMessageReceiveV1 object
            try:
                event_dict = json.loads(lark.JSON.marshal(data))
            except Exception:
                logger.warning("Failed to parse WS event, raw type: %s", type(data))
                return
            # The SDK wraps the event; extract the inner event structure
            inner_event = event_dict.get("event", event_dict)
            logger.info("WS event received: im.message.receive_v1")
            try:
                self.on_message(inner_event)
            except Exception as exc:
                logger.exception("WS on_message callback failed: %s", exc)

        # Build event dispatcher
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(_do_message_receive_v1) \
            .build()

        # Map log level
        level_map = {
            "DEBUG": lark.LogLevel.DEBUG,
            "INFO": lark.LogLevel.INFO,
            "WARN": lark.LogLevel.WARNING,
            "ERROR": lark.LogLevel.ERROR,
        }
        ll = level_map.get(self.log_level.upper(), lark.LogLevel.INFO)

        self._cli = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=event_handler,
            log_level=ll,
        )

        logger.info("Starting Feishu WebSocket client (app_id=%s)...", self.app_id[:8])
        print("[Hermes WS] Connecting to Feishu via WebSocket...")
        try:
            self._cli.start()
        except KeyboardInterrupt:
            logger.info("Feishu WS client stopped")
        except Exception as exc:
            logger.error("Feishu WS client error: %s", exc)

    def stop(self) -> None:
        if self._cli:
            try:
                self._cli.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Background pipeline runner
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Quick chat via Codex (for simple conversations, no pipeline needed)
# ---------------------------------------------------------------------------


def _resolve_codex_cmd(config: dict[str, Any]) -> list[str]:
    """Resolve the Codex exec command from config."""
    profile_name = config.get("hermes", {}).get("default_profile", "wsl_mixed")
    for pname in [profile_name, "wsl_mixed", "wsl2", "windows"]:
        profile = config.get("profiles", {}).get(pname, {})
        codex_cfg = profile.get("codex", {})
        if codex_cfg.get("enabled") and codex_cfg.get("command"):
            return list(codex_cfg["command"])
    return ["codex", "exec", "--skip-git-repo-check", "-"]




# Module-level cache for LLM classification results
_last_llm_msg_type: str | None = None
_last_llm_msg_text: str | None = None


def _classify_message(text: str) -> str:
    """Classify a message as 'chat' or 'task'.
    
    If _build_task_from_text already ran LLM analysis on the same text,
    reuse its cached result to avoid a redundant API call.
    Otherwise, fall back to a quick LLM call or regex.
    """
    global _last_llm_msg_type, _last_llm_msg_text

    # Reuse cached LLM result if the same text was already analyzed
    if _last_llm_msg_text == text and _last_llm_msg_type in ("chat", "task"):
        result = _last_llm_msg_type
        _last_llm_msg_text = None  # consume the cache
        logger.info("Reused cached LLM classification: %s", result)
        return result

    # ── Fast path: LLM classification via API ────────────────────────────
    try:
        import tomllib
        from openai import OpenAI
        with open(_codex_config_path(), "rb") as f:
            codex_cfg = tomllib.load(f)
        with open(_codex_auth_path(), "r") as f:
            auth_cfg = json.load(f)
        provider = codex_cfg.get("model_providers", {}).get("OpenAI", {})
        base_url = provider.get("base_url", "https://api.openai.com").rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        api_key = auth_cfg.get("OPENAI_API_KEY", "")
        if api_key:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": (
                        "You are a message classifier. Classify the user message into exactly one category:\n"
                        "- \"chat\": greetings, Q&A, explanations, translations, memory lookups, "
                        "anything that can be answered with plain text without executing code or calling tools\n"
                        "- \"task\": requires writing/modifying/running code, file operations, "
                        "web browsing, API calls, terminal commands, or any tool usage\n"
                        "\nReply with ONLY one word: \"chat\" or \"task\". No explanation."
                    )},
                    {"role": "user", "content": text},
                ],
                max_tokens=5,
                timeout=10,
            )
            label = resp.choices[0].message.content.strip().lower()
            if label in ("chat", "task"):
                logger.info("LLM classified as: %s", label)
                return label
    except Exception as e:
        logger.warning("LLM classification failed, using regex fallback: %s", e)

    # ── Fallback: simple regex ──────────────────────────────────────────
    task_keywords = r"\b(帮我|写|实现|修复|抓取|爬|运行|执行|部署|安装|创建|生成|开发|搜索|查询|分析|处理|下载|上传|编译|构建)\b"
    if re.search(task_keywords, text, re.IGNORECASE):
        return "task"
    return "chat"
def _load_shared_context(char_limit: int = 16000) -> str:
    """Load shared context files configured in hermes.local.toml."""
    import glob
    ctx_parts = []
    for pattern in [
        _hermes_context_path(),
    ]:
        import os
        if os.path.isfile(pattern):
            try:
                with open(pattern, "r", encoding="utf-8") as f:
                    content = f.read()
                ctx_parts.append(content[:char_limit])
            except Exception as e:
                logger.warning("Failed to read context file %s: %s", pattern, e)
    return "\n\n".join(ctx_parts) if ctx_parts else ""



def _build_messages(system_prompt: str, user_text: str, session_id: str = "") -> list[dict[str, str]]:
    """Build OpenAI-compatible messages array with conversation history."""
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    
    # Inject recent conversation history (if available)
    if session_id:
        store = _get_conv_store()
        history = store.get_history(session_id, n=8)
        if history:
            messages.extend(history)
    
    messages.append({"role": "user", "content": user_text})
    return messages



def _build_messages(system_prompt: str, user_text: str, session_id: str = "") -> list[dict[str, str]]:
    """Build OpenAI-compatible messages array with conversation history."""
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    
    # Inject recent conversation history (if available)
    if session_id:
        store = _get_conv_store()
        history = store.get_history(session_id, n=8)
        if history:
            messages.extend(history)
    
    messages.append({"role": "user", "content": user_text})
    return messages


def _codex_quick_chat(text: str, codex_cmd: list[str], session_id: str = "", timeout: int = 60) -> str:
    """Send a message directly via OpenAI API for fast conversational reply.
    Falls back to Codex CLI if API call fails.
    Returns the reply text, or empty string on failure.
    """
    import json, time as _time

    shared_ctx = _load_shared_context()
    ctx_block = ""
    if shared_ctx:
        ctx_block = "\n# === User Context (always reference this) ===\n" + shared_ctx + "\n# === End User Context ===\n"

    system_prompt = (
        "You are Hermes, an AI development assistant. Users chat with you via Feishu. "
        "Reply in concise, friendly Chinese. "
        "For greetings or chitchat, respond warmly. "
        "If asked about your capabilities, mention you can help with coding, "
        "bug fixing, deployment, etc. Keep replies under 200 characters unless user asks for detail. "
        "IMPORTANT: If the user asks who they are, use the User Context above to answer. "
        "IMPORTANT: Reply directly in plain text, no JSON, no code blocks."
    ) + ctx_block

    # --- Fast path: direct OpenAI API call ---
    try:
        logger.info("Quick chat via API starting...")
        t0 = _time.time()

        # Read API config from Codex config
        import tomllib
        with open(_codex_config_path(), "rb") as f:
            codex_cfg = tomllib.load(f)
        with open(_codex_auth_path(), "r") as f:
            auth_cfg = json.load(f)

        provider = codex_cfg.get("model_providers", {}).get("OpenAI", {})
        base_url = provider.get("base_url", "https://api.openai.com").rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        api_key = auth_cfg.get("OPENAI_API_KEY", "")

        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=_build_messages(system_prompt, text, session_id),
            max_tokens=300,
            timeout=timeout,
        )
        reply = resp.choices[0].message.content.strip()
        elapsed = _time.time() - t0
        logger.info("Quick chat via API finished in %.1fs", elapsed)
        if reply:
            return reply
    except Exception as e:
        logger.warning("API quick chat failed, falling back to Codex CLI: %s", e)

    # --- Fallback: Codex CLI (slow) ---
    import subprocess
    full_prompt = system_prompt + "\n\nUser message: " + text + "\n\nReply:"
    try:
        cmd = codex_cmd[:]
        logger.info("Quick chat via Codex CLI starting: cmd=%s", cmd[:2])
        t0 = _time.time()
        result = subprocess.run(
            cmd,
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = _time.time() - t0
        logger.info("Codex CLI quick chat finished in %.1fs (rc=%d)", elapsed, result.returncode)

        stdout = result.stdout.strip()

        if result.returncode != 0:
            logger.warning("Codex quick chat failed (rc=%d): %s", result.returncode, (result.stderr or stdout)[:500])
            return ""

        if not stdout:
            logger.warning("Codex quick chat returned empty")
            return ""

        reply = stdout

        # Try to extract from JSON if codex wraps it
        try:
            data = json.loads(reply)
            for key in ["output", "result", "content", "text"]:
                if key in data:
                    val = data[key]
                    if isinstance(val, str):
                        reply = val
                        break
                    elif isinstance(val, list):
                        for item in val:
                            if isinstance(item, dict) and item.get("text"):
                                reply = item["text"]
                                break
        except (json.JSONDecodeError, TypeError):
            pass

        # Strip markdown fences
        if "```" in reply:
            lines = reply.split("\n")
            cleaned = []
            inside = False
            for line in lines:
                if line.strip().startswith("```"):
                    inside = not inside
                    continue
                if not inside:
                    cleaned.append(line)
            reply = "\n".join(cleaned)

        return reply.strip()
    except subprocess.TimeoutExpired:
        logger.warning("Codex quick chat timed out after %ds", timeout)
        return ""
    except Exception as exc:
        logger.warning("Codex quick chat error: %s", exc)
        return ""


def _run_quick_chat_async(
    codex_cmd: list[str],
    text: str,
    sender: "FeishuAppSender | None",
    reply_target: "tuple[str, str] | None",
    session_id: str = "",
) -> None:
    """Run a quick Codex chat in background and reply via Feishu."""
    def _notify(msg: str) -> None:
        if sender and reply_target:
            rid, rtype = reply_target
            try:
                sender.send_text(rid, rtype, msg)
            except Exception as exc:
                logger.warning("Failed to send Feishu notification: %s", exc)
    
    try:
        reply = _codex_quick_chat(text, codex_cmd, session_id=session_id)
        # Save user message and assistant reply to conversation store
        if session_id:
            store = _get_conv_store()
            store.add_message(session_id, "user", text)
            if reply:
                store.add_message(session_id, "assistant", reply)
        if reply:
            _notify(reply)
        else:
            _notify("抱歉，回复超时了，请稍后再试。")
    except Exception as exc:
        logger.exception("Quick chat failed: %s", exc)
        _notify(f"回复失败：{exc}")



def _run_pipeline_async(
    config_path: Path,
    task_json: dict[str, Any],
    pipeline: str,
    sender: "FeishuAppSender | None",
    reply_target: "tuple[str, str] | None",
    session_id: str = "",
) -> None:
    """Run a Hermes pipeline in a background thread and notify via Feishu."""
    from .runner import run_pipeline

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".task.json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(task_json, f, ensure_ascii=False, indent=2)
        task_file = Path(f.name)

    def _notify(msg: str) -> None:
        if sender and reply_target:
            rid, rtype = reply_target
            try:
                sender.send_text(rid, rtype, msg)
            except Exception as exc:
                logger.warning("Failed to send Feishu notification: %s", exc)

    try:
        # Save to conversation store
        if session_id:
            _get_conv_store().add_message(session_id, "user", task_json.get("goal", ""))
        # Save to conversation store
        if session_id:
            _get_conv_store().add_message(session_id, "user", task_json.get("goal", ""))
        logger.info("Pipeline task starting: goal=%.100s", task_json.get('goal', ''))
        _notify(f"\U0001f680 收到任务，开始执行...\n目标：{task_json.get('goal', '(未指定)')}")
        logger.info("Pipeline notify sent, calling run_pipeline...")
        run_dir = run_pipeline(config_path, task_file, pipeline, None)
        logger.info("Pipeline run_pipeline returned: %s", run_dir)

        # Read run_summary.json to extract results
        summary_path = Path(run_dir) / "run_summary.json"
        result_msg = f"\u2705 任务完成！\n运行目录：{run_dir}"
        if summary_path.exists():
            try:
                with open(summary_path, "r", encoding="utf-8") as sf:
                    summary = json.load(sf)
                # Extract executor and reviewer artifacts
                stages = summary.get("stages", [])
                for s in stages:
                    stage_name = s.get("stage", "")
                    artifact = s.get("artifact", {})
                    if stage_name == "executor" and artifact.get("summary"):
                        result_msg += f"\n\n📋 执行结果：{artifact['summary']}"
                    if stage_name == "reviewer" and artifact.get("verdict"):
                        verdict = artifact['verdict']
                        icon = "✅" if verdict == "pass" else "⚠️"
                        result_msg += f"\n\n{icon} 审核结论：{verdict}"
                        if artifact.get("summary"):
                            result_msg += f"\n{artifact['summary']}"
                        findings = artifact.get("findings", [])
                        if findings:
                            result_msg += f"\n\n发现的问题（{len(findings)}项）："
                            for i, f_item in enumerate(findings[:5], 1):
                                sev = f_item.get("severity", "")
                                issue = f_item.get("issue", "")[:120]
                                result_msg += f"\n{i}. [{sev}] {issue}"
                            if len(findings) > 5:
                                result_msg += f"\n... 还有 {len(findings)-5} 项"
                # Check for errors
                if summary.get("status") == "failed":
                    result_msg = f"\u274c 任务失败：{summary.get('error', '未知错误')}"
            except Exception as e:
                logger.warning("Failed to parse run_summary: %s", e)

        _notify(result_msg)
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        _notify(f"\u274c 任务失败：{exc}")
    finally:
        task_file.unlink(missing_ok=True)


def _build_task_from_text(text: str, session_id: str = "") -> tuple[dict[str, Any], str]:
    """Convert raw Feishu message text into a TaskSpec-compatible dict.
    
    Uses LLM (gpt-4o-mini) to detect intent and classify simultaneously.
    Falls back to simple keyword matching if API call fails.
    """
    from . import router

    clean = re.sub(r"@\S+", "", text).strip()

    # ── Fast path: LLM-based intent + classification ────────────────────
    try:
        import tomllib
        from openai import OpenAI
        with open(_codex_config_path(), "rb") as f:
            codex_cfg = tomllib.load(f)
        with open(_codex_auth_path(), "r") as f:
            auth_cfg = json.load(f)
        provider = codex_cfg.get("model_providers", {}).get("OpenAI", {})
        base_url = provider.get("base_url", "https://api.openai.com").rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        api_key = auth_cfg.get("OPENAI_API_KEY", "")
        if api_key:
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": (
                        "You are a task analyzer for a coding assistant. "
                        "Classify the user message into exactly two fields:\n"
                        '1. \"intent\": one of: implement, fix, review, audit, research, verify\n'
                        "   - implement: build new features, create files, develop projects\n"
                        "   - fix: fix bugs, repair broken code, correct errors\n"
                        "   - review: code review, check quality, inspect code\n"
                        "   - audit: security audit, compliance check\n"
                        "   - research: investigate, explore, analyze (non-coding)\n"
                        "   - verify: test, validate, smoke test\n"
                        '2. \"msg_type\": one of: chat, task\n'
                        "   - chat: can be answered with plain text (greetings, Q&A, translations, explanations)\n"
                        "   - task: requires code execution, file operations, web browsing, tool usage\n"
                        '\nReply with ONLY valid JSON: {\"intent\": \"...\", \"msg_type\": \"...\"}'
                    )},
                    {"role": "user", "content": text},
                ],
                max_tokens=30,
                timeout=10,
            )
            raw = resp.choices[0].message.content.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
            analysis = json.loads(raw)
            intent = analysis.get("intent", "implement")
            msg_type = analysis.get("msg_type", "task")
            
            # Cache msg_type for _classify_message to use
            _last_llm_msg_type = msg_type
            _last_llm_msg_text = text
            
            logger.info("LLM analysis: intent=%s msg_type=%s", intent, msg_type)
        else:
            raise ValueError("No API key")
    except Exception as e:
        logger.warning("LLM intent analysis failed, using keyword fallback: %s", e)
        intent = "implement"
        lower = clean.lower()
        if any(w in lower for w in ("review", "审查", "检查", "check")):
            intent = "review"
        elif any(w in lower for w in ("fix", "修复", "bug", "错误")):
            intent = "fix"
        elif any(w in lower for w in ("audit", "审计")):
            intent = "audit"
        _last_llm_msg_type = None
        _last_llm_msg_text = text

    # Inject conversation context into task notes
    task_notes = ["Task received via Feishu message"]
    if session_id:
        store = _get_conv_store()
        conv_summary = store.get_summary(session_id)
        if conv_summary:
            task_notes.append(f"Recent conversation context:\n{conv_summary}")
    
    task_dict = {
        "id": f"feishu-{uuid.uuid4().hex[:8]}",
        "intent": intent,
        "goal": clean,
        "cwd": os.path.expanduser("~"),
        "constraints": [],
        "context_files": [],
        "notes": task_notes,
    }

    # Use router to select pipeline
    pipeline_name = router.choose_pipeline(task_dict)
    logger.info("Router selected pipeline: %s (intent=%s)", pipeline_name, intent)

    return task_dict, pipeline_name
class HermesHandler(http.server.BaseHTTPRequestHandler):
    """Handle incoming Feishu event callbacks."""

    config_path: Path
    config: dict[str, Any]
    sender: "FeishuAppSender | None"

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info(fmt, *args)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _json_resp(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json_resp(200, {"status": "ok", "service": "hermes"})
        else:
            self._json_resp(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        raw = self._read_body()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json_resp(400, {"error": "invalid json"})
            return

        # Feishu URL verification
        if payload.get("type") == "url_verification":
            challenge = payload.get("challenge", "")
            logger.info("Feishu URL verification OK")
            self._json_resp(200, {"challenge": challenge})
            return

        # Feishu event v2
        header = payload.get("header", {})
        event_type = header.get("event_type", "")
        event = payload.get("event", {})
        logger.info("Feishu event: %s", event_type)

        if event_type == "im.message.receive_v1":
            self._handle_message(event)

        self._json_resp(200, {"code": 0})

    def _handle_message(self, event: dict[str, Any]) -> None:
        msg = event.get("message", {})
        sender_info = event.get("sender", {})
        content_raw = msg.get("content", "{}")
        try:
            content = json.loads(content_raw)
        except json.JSONDecodeError:
            content = {}
        text = content.get("text", "").strip()
        if not text:
            return

        chat_type = msg.get("chat_type", "p2p")
        if chat_type == "p2p":
            reply_id = sender_info.get("sender_id", {}).get("open_id", "")
            reply_type = "open_id"
        else:
            reply_id = msg.get("chat_id", "")
            reply_type = "chat_id"

        logger.info("Message from %s (%s): %.100s", reply_id, chat_type, text)

        # Classify message: quick chat vs development task
        msg_type = _classify_message(text)
        logger.info("Message classified as: %s", msg_type)

        # Derive session_id from reply_id (user or chat)
        session_id = reply_id if reply_id else ""

        if msg_type == "chat":
            # Quick reply via Claude - no pipeline needed
            codex_cmd = _resolve_codex_cmd(self.config)
            t = threading.Thread(
                target=_run_quick_chat_async,
                args=(codex_cmd, text, self.sender, (reply_id, reply_type), session_id),
                daemon=True,
            )
            t.start()
        else:
            # Development task - run full pipeline
            task_json, pipeline = _build_task_from_text(text, session_id=session_id)
            t = threading.Thread(
                target=_run_pipeline_async,
                args=(self.config_path, task_json, pipeline, self.sender, (reply_id, reply_type), session_id),
                daemon=True,
            )
            t.start()


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

class HermesServer:
    """Wraps HTTPServer with Hermes config injection."""

    def __init__(
        self,
        config_path: Path,
        config: dict[str, Any],
        host: str = "0.0.0.0",
        port: int = 8765,
    ) -> None:
        self.config_path = config_path
        self.config = config
        self.host = host
        self.port = port

        feishu_cfg = config.get("feishu", {})
        app_cfg = feishu_cfg.get("app", {})
        app_id = app_cfg.get("app_id", "")
        app_secret = app_cfg.get("app_secret", "")
        prefix = app_cfg.get("message_prefix", "[Hermes]")
        self.sender: FeishuAppSender | None = (
            FeishuAppSender(app_id, app_secret, prefix) if app_id and app_secret else None
        )

    def run(self, mode: str = "http") -> None:
        """Run Hermes server. mode: 'http' (webhook) or 'websocket' (long connection)."""
        config_path = self.config_path
        config = self.config
        sender = self.sender

        if mode == "websocket":
            self._run_websocket(sender)
        else:
            self._run_http(config_path, config, sender)

    def _run_http(self, config_path, config, sender) -> None:
        """Traditional HTTP webhook mode (needs cloudflared tunnel)."""
        class _Handler(HermesHandler):
            pass

        _Handler.config_path = config_path
        _Handler.config = config
        _Handler.sender = sender

        srv = http.server.HTTPServer((self.host, self.port), _Handler)
        logger.info("Hermes HTTP server on %s:%d", self.host, self.port)
        print(f"[Hermes] HTTP server started  http://{self.host}:{self.port}")
        print(f"[Hermes] Health check:        http://127.0.0.1:{self.port}/health")
        print(f"[Hermes] Feishu sender:       {'enabled' if sender else 'disabled (no app_id/app_secret)'}")
        srv.serve_forever()

    def _run_websocket(self, sender) -> None:
        """WebSocket long-connection mode (no tunnel needed!)."""
        feishu_cfg = self.config.get("feishu", {})
        app_cfg = feishu_cfg.get("app", {})
        app_id = app_cfg.get("app_id", "")
        app_secret = app_cfg.get("app_secret", "")

        if not app_id or not app_secret:
            print("[Hermes WS] ERROR: feishu.app.app_id and app_secret required for websocket mode")
            return

        def _on_message(event: dict) -> None:
            """Handle incoming message event from WS — same logic as HTTP handler."""
            config_path = self.config_path
            config = self.config

            msg = event.get("message", {})
            sender_info = event.get("sender", {})
            content_raw = msg.get("content", "{}")
            try:
                content = json.loads(content_raw)
            except json.JSONDecodeError:
                content = {}
            text = content.get("text", "").strip()
            if not text:
                return

            chat_type = msg.get("chat_type", "p2p")
            if chat_type == "p2p":
                reply_id = sender_info.get("sender_id", {}).get("open_id", "")
                reply_type = "open_id"
            else:
                reply_id = msg.get("chat_id", "")
                reply_type = "chat_id"

            logger.info("WS Message from %s (%s): %.100s", reply_id, chat_type, text)

            # Classify and dispatch
            msg_type = _classify_message(text)
            logger.info("Message classified as: %s", msg_type)

            # Derive session_id from reply_id
            session_id = reply_id if reply_id else ""

            if msg_type == "chat":
                codex_cmd = _resolve_codex_cmd(config)
                t = threading.Thread(
                    target=_run_quick_chat_async,
                    args=(codex_cmd, text, sender, (reply_id, reply_type), session_id),
                    daemon=True,
                )
                t.start()
            else:
                task_json, pipeline = _build_task_from_text(text, session_id=session_id)
                t = threading.Thread(
                    target=_run_pipeline_async,
                    args=(config_path, task_json, pipeline, sender, (reply_id, reply_type), session_id),
                    daemon=True,
                )
                t.start()

        ws_client = FeishuWSClient(
            app_id=app_id,
            app_secret=app_secret,
            on_message=_on_message,
        )

        # Start WS client in background thread
        ws_client.start(in_thread=False)
