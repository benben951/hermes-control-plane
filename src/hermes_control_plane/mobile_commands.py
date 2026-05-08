"""Phone-first command handling and approval gates for Feishu control."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

CommandKind = Literal["chat", "task", "fast", "review", "status", "handoff", "tail", "approve"]


@dataclass
class MobileCommand:
    kind: CommandKind
    arg: str = ""


@dataclass
class PendingAction:
    action_id: str
    session_id: str
    text: str
    risk: str
    created_at: float = field(default_factory=time.time)


class PendingActionStore:
    """Small in-memory approval store keyed by action id."""

    def __init__(self, ttl_seconds: float = 30 * 60, max_actions: int = 200) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_actions = max_actions
        self._actions: dict[str, PendingAction] = {}
        self._lock = threading.Lock()

    def create(self, session_id: str, text: str, risk: str) -> PendingAction:
        with self._lock:
            self._evict_locked()
            action_id = f"approve-{uuid.uuid4().hex[:8]}"
            action = PendingAction(
                action_id=action_id,
                session_id=session_id,
                text=text,
                risk=risk,
            )
            self._actions[action_id] = action
            return action

    def pop(self, action_id: str, session_id: str) -> PendingAction | None:
        with self._lock:
            self._evict_locked()
            action = self._actions.get(action_id)
            if not action or action.session_id != session_id:
                return None
            return self._actions.pop(action_id)

    def list_for_session(self, session_id: str) -> list[PendingAction]:
        with self._lock:
            self._evict_locked()
            return [a for a in self._actions.values() if a.session_id == session_id]

    def _evict_locked(self) -> None:
        now = time.time()
        expired = [
            action_id
            for action_id, action in self._actions.items()
            if now - action.created_at > self.ttl_seconds
        ]
        for action_id in expired:
            del self._actions[action_id]
        while len(self._actions) > self.max_actions:
            oldest = min(self._actions.values(), key=lambda item: item.created_at)
            del self._actions[oldest.action_id]


_pending_store = PendingActionStore()


def get_pending_store() -> PendingActionStore:
    return _pending_store


def reset_pending_store() -> None:
    global _pending_store
    _pending_store = PendingActionStore()


def parse_mobile_command(text: str) -> MobileCommand | None:
    match = re.match(
        r"^\s*/(chat|task|fast|review|status|handoff|tail|approve)\b\s*(.*)$",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return MobileCommand(kind=match.group(1).lower(), arg=match.group(2).strip())  # type: ignore[arg-type]


HIGH_RISK_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(kaggle\s+competitions\s+submit|kaggle\s+submit)\b|提交\s*kaggle|kaggle.*提交", "Kaggle submission"),
    (r"leaderboard|榜单|评测|evaluation|evaluate|创建.*评估|提交.*评测", "leaderboard evaluation"),
    (r"发布模型|publish\s+model|model\s+publish|上传模型|平台.*发布", "model publishing"),
    (r"提交.*训练|启动.*训练|submit.*training|start.*training|平台.*提交", "platform training submission"),
    (r"\bgit\s+push\b|\bgh\s+pr\s+create\b|\bgh\s+pr\s+merge\b|推送到\s*github|创建\s*pr", "GitHub write action"),
    (r"\brm\s+-rf\b|\bdelete\b|删除|清空|wipe|remove\s+.*-r", "destructive filesystem action"),
    (r"auth\.json|cookie|cookies|token|secret|\.copaw\.secret|\.claude|密码|密钥", "secret or credential access"),
)


def detect_high_risk(text: str) -> str | None:
    for pattern, risk in HIGH_RISK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return risk
    return None


def format_pending_action(action: PendingAction) -> str:
    return (
        "需要确认后才会执行。\n"
        f"Action: {action.action_id}\n"
        f"Risk: {action.risk}\n"
        f"Goal: {action.text[:300]}\n"
        f"回复 /approve {action.action_id} 继续。"
    )


def render_status(target: str, config: dict[str, Any]) -> str:
    target = (target or "help").strip().lower()
    runs_root = Path(config.get("hermes", {}).get("runs_root", str(Path.home() / ".hermes" / "runs")))

    if target in {"", "help"}:
        return (
            "在线。可用命令：/status taac、/status kaggle、/handoff、/tail hermes、"
            "/chat、/fast、/task、/review、/approve <id>。"
        )
    if target == "taac":
        return _render_taac_status()
    if target == "kaggle":
        return _render_kaggle_status()
    if target in {"runs", "hermes"}:
        return _render_runs_status(runs_root)
    return "未知状态目标。可用：/status taac、/status kaggle、/status hermes。"


def render_handoff() -> str:
    taac = _render_taac_status()
    kaggle = _render_kaggle_status()
    return f"今日交接：\n\n[TAAC]\n{taac}\n\n[Kaggle]\n{kaggle}"


def render_tail(target: str, config: dict[str, Any], max_lines: int = 20) -> str:
    target = (target or "hermes").strip().lower()
    if target != "hermes":
        return "当前只支持 /tail hermes。"
    log_path = Path(config.get("hermes", {}).get("log_path", "/tmp/hermes_server.log"))
    if not log_path.exists():
        return f"未找到日志：{log_path}"
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
    clean_lines = [_redact_sensitive(line) for line in lines]
    return "Hermes 最近日志：\n" + "\n".join(clean_lines[-max_lines:])


def _render_taac_status() -> str:
    path = Path("/mnt/c/Users/jie13/Documents/Playground/taac-2026-industrial/configs/platform_experiments.yaml")
    if not path.exists():
        return "未找到 TAAC 配置文件；请确认项目路径。"
    text = path.read_text(encoding="utf-8", errors="replace")
    fields = {
        "best validation AUC": _find_yaml_scalar(text, "validation_auc"),
        "leaderboard AUC": _find_yaml_scalar(text, "leaderboard_auc"),
        "inference time": _find_yaml_scalar(text, "inference_time_seconds"),
    }
    active = _find_first_name_after_section(text, "active_jobs")
    prepared = _find_first_name_after_section(text, "prepared_jobs")
    return (
        f"best validation AUC: {fields['best validation AUC'] or 'unknown'}\n"
        f"leaderboard AUC: {fields['leaderboard AUC'] or 'unknown'}\n"
        f"inference time: {fields['inference time'] or 'unknown'}s\n"
        f"active: {active or 'none'}\n"
        f"prepared: {prepared or 'none'}"
    )


def _render_kaggle_status() -> str:
    path = Path("/mnt/c/Users/jie13/Documents/Playground/kaggle-nemotron-reasoning/data/processed/sft/summary.json")
    docs = Path("/mnt/c/Users/jie13/Documents/Playground/kaggle-nemotron-reasoning/docs/EXPERIMENTS.md")
    if not path.exists():
        return "未找到 Kaggle SFT summary；请确认项目路径。"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
    train_rows = data.get("train_rows") or data.get("train_count") or data.get("num_train")
    val_rows = data.get("val_rows") or data.get("val_count") or data.get("num_val")
    seed = data.get("seed")
    latest = ""
    if docs.exists():
        rows = [line for line in docs.read_text(encoding="utf-8", errors="replace").splitlines() if line.startswith("|") and "Run" not in line and "---" not in line]
        if rows:
            latest = rows[-1].split("|")[1].strip()
    return (
        f"SFT train rows: {train_rows or 'unknown'}\n"
        f"SFT val rows: {val_rows or 'unknown'}\n"
        f"seed: {seed or 'unknown'}\n"
        f"latest experiment: {latest or 'unknown'}\n"
        "next: LoRA smoke notebook before real submission."
    )


def _render_runs_status(runs_root: Path) -> str:
    if not runs_root.exists():
        return f"未找到 runs 目录：{runs_root}"
    runs = sorted((p for p in runs_root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        return "Hermes 在线，但暂无 run 记录。"
    latest = runs[0]
    summary_path = latest / "run_summary.json"
    status = "unknown"
    pipeline = "unknown"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            status = str(summary.get("status", "unknown"))
            pipeline = str(summary.get("pipeline", "unknown"))
        except json.JSONDecodeError:
            pass
    return f"latest run: {latest.name}\nstatus: {status}\npipeline: {pipeline}"


def _find_yaml_scalar(text: str, key: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(key)}:\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip().strip('"') if match else None


def _find_first_name_after_section(text: str, section: str) -> str | None:
    match = re.search(rf"^{re.escape(section)}:\s*\n(?P<body>(?:\s+.*\n)+)", text, re.MULTILINE)
    if not match:
        return None
    name_match = re.search(r"^\s*-\s*name:\s*(.+?)\s*$", match.group("body"), re.MULTILINE)
    return name_match.group(1).strip().strip('"') if name_match else None


def _redact_sensitive(text: str) -> str:
    text = re.sub(r"(access_key=)[^&\s]+", r"\1[redacted]", text)
    text = re.sub(r"(ticket=)[^&\s]+", r"\1[redacted]", text)
    text = re.sub(r"(Authorization:\s*Bearer\s+)[A-Za-z0-9._-]+", r"\1[redacted]", text, flags=re.IGNORECASE)
    return text
