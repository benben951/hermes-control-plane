"""In-memory conversation history for per-user session tracking.

Each user (identified by open_id or chat_id) maintains a rolling buffer of
recent messages. This module is zero-dependency (stdlib only) and thread-safe.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_TURNS = 20
DEFAULT_MAX_AGE_SECONDS = 24 * 3600.0
DEFAULT_MAX_SESSIONS = 500


@dataclass
class Message:
    role: str  # "user" | "assistant"
    text: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.text}


@dataclass
class Session:
    """A single user's conversation session."""

    session_id: str
    messages: list[Message] = field(default_factory=list)
    max_turns: int = DEFAULT_MAX_TURNS
    max_age: float = DEFAULT_MAX_AGE_SECONDS

    @property
    def last_activity(self) -> float:
        if self.messages:
            return self.messages[-1].ts
        return 0.0

    def is_expired(self) -> bool:
        if not self.messages:
            return True
        return (time.time() - self.last_activity) > self.max_age

    def add(self, role: str, text: str) -> None:
        self.messages.append(Message(role=role, text=text))
        self._trim()

    def _trim(self) -> None:
        """Keep only the most recent max_turns messages."""
        if len(self.messages) > self.max_turns:
            self.messages = self.messages[-self.max_turns:]

    def get_recent(self, n: int = 10) -> list[dict[str, str]]:
        """Return the most recent *n* messages as OpenAI-compatible dicts."""
        recent = self.messages[-n:] if n else self.messages
        return [m.to_dict() for m in recent]

    def get_summary(self, max_chars: int = 2000) -> str:
        """Return a text summary of the conversation for task context."""
        if not self.messages:
            return ""
        lines: list[str] = []
        for m in self.messages[-6:]:  # last 6 messages
            label = "User" if m.role == "user" else "Hermes"
            # Truncate very long messages
            text = m.text if len(m.text) <= 500 else m.text[:500] + "..."
            lines.append(f"[{label}]: {text}")
        summary = "\n".join(lines)
        if len(summary) > max_chars:
            summary = summary[:max_chars] + "\n[...truncated]"
        return summary

    def clear(self) -> None:
        self.messages.clear()


class ConversationStore:
    """Thread-safe in-memory store for user sessions."""

    def __init__(
        self,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        default_max_turns: int = DEFAULT_MAX_TURNS,
        default_max_age: float = DEFAULT_MAX_AGE_SECONDS,
    ) -> None:
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()
        self._max_sessions = max_sessions
        self._default_max_turns = default_max_turns
        self._default_max_age = default_max_age

    def reconfigure(
        self,
        *,
        max_sessions: int | None = None,
        default_max_turns: int | None = None,
        default_max_age: float | None = None,
    ) -> None:
        with self._lock:
            if max_sessions is not None:
                self._max_sessions = max_sessions
            if default_max_turns is not None:
                self._default_max_turns = default_max_turns
            if default_max_age is not None:
                self._default_max_age = default_max_age
            for session in self._sessions.values():
                session.max_turns = self._default_max_turns
                session.max_age = self._default_max_age
                session._trim()
            self._evict_expired()

    def get_or_create(self, session_id: str) -> Session:
        with self._lock:
            self._evict_expired()
            if session_id in self._sessions:
                session = self._sessions[session_id]
                # Move to end (most recently used)
                self._sessions.move_to_end(session_id)
                return session
            session = Session(
                session_id=session_id,
                max_turns=self._default_max_turns,
                max_age=self._default_max_age,
            )
            self._sessions[session_id] = session
            logger.info("New conversation session created: %s", session_id)
            return session

    def add_message(self, session_id: str, role: str, text: str) -> Session:
        session = self.get_or_create(session_id)
        session.add(role, text)
        return session

    def get_history(self, session_id: str, n: int = 10) -> list[dict[str, str]]:
        session = self._sessions.get(session_id)
        if not session or session.is_expired():
            return []
        return session.get_recent(n)

    def get_summary(self, session_id: str, max_chars: int = 2000) -> str:
        session = self._sessions.get(session_id)
        if not session or session.is_expired():
            return ""
        return session.get_summary(max_chars)

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

    def clear_all(self) -> int:
        with self._lock:
            count = len(self._sessions)
            self._sessions.clear()
            return count

    def stats(self) -> dict[str, Any]:
        with self._lock:
            active = sum(1 for s in self._sessions.values() if not s.is_expired())
            return {
                "total_sessions": len(self._sessions),
                "active_sessions": active,
                "expired_sessions": len(self._sessions) - active,
            }

    def _evict_expired(self) -> None:
        """Remove expired sessions and enforce max_sessions limit."""
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
        for sid in expired:
            del self._sessions[sid]
        # Evict oldest if over limit
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)


# -- Module-level singleton --

_store: ConversationStore | None = None


def configure_store(
    *,
    max_sessions: int | None = None,
    default_max_turns: int | None = None,
    default_max_age: float | None = None,
) -> ConversationStore:
    global _store
    if _store is None:
        _store = ConversationStore(
            max_sessions=max_sessions if max_sessions is not None else DEFAULT_MAX_SESSIONS,
            default_max_turns=default_max_turns if default_max_turns is not None else DEFAULT_MAX_TURNS,
            default_max_age=default_max_age if default_max_age is not None else DEFAULT_MAX_AGE_SECONDS,
        )
    else:
        _store.reconfigure(
            max_sessions=max_sessions,
            default_max_turns=default_max_turns,
            default_max_age=default_max_age,
        )
    return _store


def get_store() -> ConversationStore:
    return configure_store()


def reset_store() -> None:
    global _store
    _store = None
