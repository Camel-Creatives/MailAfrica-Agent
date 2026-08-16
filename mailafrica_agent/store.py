from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiosqlite


@dataclass
class ConversationTurn:
    role: str  # user | assistant
    content: str
    message_id: int
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Store:
    """SQLite-backed conversation-memory store.

    Auto-reply *configuration* now lives in MailAfrica's own database (the
    single source of truth shared with the web app); this store keeps only
    thread history, so the LLM sees the full conversation. Threads are keyed
    by normalized subject + the original sender, because MailAfrica's inbound
    parser exposes headers but not In-Reply-To, so reply chains are best
    reconstructed from (subject, sender). Replies sent by the agent are
    recorded back into the same thread.
    """

    def __init__(self, path: str):
        self.path = path

    async def connect(self) -> None:
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        # WAL + busy timeout let the webhook process and the MCP stdio
        # process share the same SQLite file without "database is locked".
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA busy_timeout=5000")
        await         self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_key  TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                message_id  INTEGER NOT NULL,
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conversations_thread
                ON conversations (thread_key, created_at);
            """
        )
        await self.db.commit()

    async def close(self) -> None:
        await self.db.close()

    # --- conversations ------------------------------------------------------

    @staticmethod
    def thread_key(subject: str, sender: str) -> str:
        """Group a message into a conversation with its (normalized) thread."""
        normalized = re.sub(r"^\s*(re|fw|fwd)\s*:\s*", "", subject, flags=re.IGNORECASE)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return f"{sender.lower()}:::{normalized or '(no subject)'}"

    async def append_turn(
        self, thread_key: str, role: str, content: str, message_id: int
    ) -> None:
        cur = await self.db.execute(
            "INSERT INTO conversations (thread_key, role, content, message_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                thread_key,
                role,
                content,
                message_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await cur.close()
        await self.db.commit()

    async def get_thread(self, thread_key: str, limit: int = 40) -> list[ConversationTurn]:
        cur = await self.db.execute(
            "SELECT role, content, message_id, created_at FROM conversations "
            "WHERE thread_key = ? ORDER BY id DESC LIMIT ?",
            (thread_key, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        turns = [
            ConversationTurn(
                role=row["role"],
                content=row["content"],
                message_id=row["message_id"],
                created_at=row["created_at"],
            )
            for row in reversed(rows)
        ]
        return turns
