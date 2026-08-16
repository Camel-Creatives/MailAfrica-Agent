from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiosqlite


@dataclass
class AddressAgent:
    """Per-inbound-address auto-reply configuration."""

    address_id: int
    mode: str = "off"  # auto | draft | off
    persona: str | None = None
    enabled: bool = True
    reply_from_domain_id: int | None = None
    reply_from_address: str | None = None

    def effective_persona(self, default: str) -> str:
        return self.persona or default


@dataclass
class ConversationTurn:
    role: str  # user | assistant
    content: str
    message_id: int
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Store:
    """SQLite-backed conversation + agent-config store.

    Threads are keyed by normalized subject + the original sender, because
    MailAfrica's inbound parser exposes headers but not In-Reply-To, so reply
    chains are best reconstructed from (subject, sender). Replies sent by the
    agent are recorded back into the same thread so the LLM sees the full
    conversation.
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
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_addresses (
                address_id             INTEGER PRIMARY KEY,
                mode                   TEXT NOT NULL DEFAULT 'off',
                persona                TEXT,
                enabled                INTEGER NOT NULL DEFAULT 1,
                reply_from_domain_id   INTEGER,
                reply_from_address     TEXT
            );

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

    # --- agent config -------------------------------------------------------

    async def get_address_agent(self, address_id: int) -> AddressAgent | None:
        cur = await self.db.execute(
            "SELECT address_id, mode, persona, enabled, reply_from_domain_id, reply_from_address "
            "FROM agent_addresses WHERE address_id = ?",
            (address_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        if row is None:
            return None
        return AddressAgent(
            address_id=row["address_id"],
            mode=row["mode"],
            persona=row["persona"],
            enabled=bool(row["enabled"]),
            reply_from_domain_id=row["reply_from_domain_id"],
            reply_from_address=row["reply_from_address"],
        )

    async def set_address_agent(
        self,
        address_id: int,
        mode: str | None = None,
        persona: str | None = None,
        reply_from_domain_id: int | None = None,
        reply_from_address: str | None = None,
    ) -> AddressAgent:
        cur = await self.db.execute(
            "INSERT INTO agent_addresses (address_id, mode) VALUES (?, 'off') "
            "ON CONFLICT(address_id) DO NOTHING",
            (address_id,),
        )
        await cur.close()
        if mode is not None:
            await self._set_field(address_id, "mode", mode)
        if persona is not None:
            await self._set_field(address_id, "persona", persona)
        if reply_from_domain_id is not None:
            await self._set_field(address_id, "reply_from_domain_id", str(reply_from_domain_id))
        if reply_from_address is not None:
            await self._set_field(address_id, "reply_from_address", reply_from_address)
        await self.db.commit()
        existing = await self.get_address_agent(address_id)
        assert existing is not None
        return existing

    async def _set_field(self, address_id: int, column: str, value: str) -> None:
        cur = await self.db.execute(
            f"UPDATE agent_addresses SET {column} = ? WHERE address_id = ?", (value, address_id)
        )
        await cur.close()

    async def list_address_agents(self) -> list[AddressAgent]:
        cur = await self.db.execute("SELECT * FROM agent_addresses")
        rows = await cur.fetchall()
        await cur.close()
        return [
            AddressAgent(
                address_id=row["address_id"],
                mode=row["mode"],
                persona=row["persona"],
                enabled=bool(row["enabled"]),
                reply_from_domain_id=row["reply_from_domain_id"],
                reply_from_address=row["reply_from_address"],
            )
            for row in rows
        ]

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
