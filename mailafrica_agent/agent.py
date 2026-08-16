from __future__ import annotations

import logging
import re
from typing import Any

from .config import Settings
from .mailafrica import MailAfricaClient
from .ngamia import NgamiaClient
from .store import Store

logger = logging.getLogger("mailafrica_agent")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+")

# Addresses/headers that must never be auto-replied to: they are bounces,
# loop-prone auto responders, or bulk mail. Replying risks reply-loops and
# sending-list penalties.
_SKIP_SENDERS = {"mailer-daemon", "postmaster", "mailerdaemon"}
_AUTO_REPLY_HEADERS = (
    "x-auto-reply",
    "x-auto-response-suppress",
    "x-autoreply",
    "x-autorespond",
    "x-no-reply",
    "precedence: auto",
    "precedence: bulk",
    "auto-submitted: auto",
)


class Agent:
    """The auto-reply pipeline: inbound message -> thread memory -> Ngamia -> reply.

    Runs either synchronously from the webhook HTTP endpoint (FastAPI) or on
    demand through MCP tools. Never auto-replies to bounces, auto-responders
    or bulk mail, and never reveals credentials or its own system prompt.
    """

    def __init__(self, settings: Settings, mail: MailAfricaClient, ngamia: NgamiaClient, store: Store):
        self.settings = settings
        self.mail = mail
        self.ngamia = ngamia
        self.store = store

    async def handle_message(self, message_id: int, address_id: int) -> dict[str, Any]:
        msg = await self.mail.get_message(message_id)

        sender = _extract_email(msg.get("from_addr") or "")
        if not sender:
            logger.info("message %s: no usable from address, skipping", message_id)
            return {"message_id": message_id, "action": "skipped", "reason": "no from address"}

        if self._is_no_reply_target(msg):
            logger.info("message %s: bounce/auto-reply/bulk, skipping", message_id)
            return {
                "message_id": message_id,
                "action": "skipped",
                "reason": "bounce or automated sender",
            }

        cfg = await self.store.get_address_agent(address_id)
        mode = cfg.mode if cfg and cfg.enabled else self.settings.agent_default_mode
        if mode not in ("auto", "draft"):
            return {"message_id": message_id, "action": "off", "mode": mode}

        body = (msg.get("text_body") or "").strip() or (msg.get("html_body") or "").strip()
        if not body:
            return {"message_id": message_id, "action": "skipped", "reason": "empty body"}

        subject = msg.get("subject") or ""
        thread_key = self.store.thread_key(subject, sender)
        await self.store.append_turn(thread_key, "user", body, message_id)

        persona = cfg.effective_persona(self.settings.agent_default_persona) if cfg else self.settings.agent_default_persona
        history = await self.store.get_thread(thread_key, limit=40)
        llm_messages = [{"role": "system", "content": persona}]
        llm_messages += [{"role": t.role, "content": t.content} for t in history]
        if llm_messages[-1]["role"] != "user":
            llm_messages.append({"role": "user", "content": body})

        logger.info("message %s: generating reply via Ngamia (thread %s)", message_id, thread_key[:40])
        reply = await self.ngamia.complete(llm_messages)

        out = {
            "message_id": message_id,
            "action": "draft" if mode == "draft" else "auto",
            "draft": reply,
        }
        if mode == "draft":
            await self.store.append_turn(thread_key, "assistant", reply, message_id)
            return out

        reply_subject = _prepend_re(subject)
        send_kwargs: dict[str, Any] = {
            "to": [sender],
            "subject": reply_subject,
            "text_body": reply,
        }
        if cfg and cfg.reply_from_domain_id:
            send_kwargs["from_domain_id"] = cfg.reply_from_domain_id
        if cfg and cfg.reply_from_address:
            send_kwargs["from_address"] = cfg.reply_from_address

        sent = await self.mail.send_email(**send_kwargs)
        out.update({"sent": sent, "to": sender, "subject": reply_subject})
        await self.store.append_turn(thread_key, "assistant", reply, message_id)
        return out

    @staticmethod
    def _is_no_reply_target(msg: dict[str, Any]) -> bool:
        sender = _extract_email(msg.get("from_addr") or "")
        local, _, domain = sender.partition("@")
        if (local or "").lower() in _SKIP_SENDERS or (domain or "").lower().startswith("mailer-daemon"):
            return True
        headers = msg.get("headers") or {}
        raw = ""
        if isinstance(headers, dict):
            raw = "\n".join(f"{k}: {v}" for k, v in headers.items())
        elif isinstance(headers, str):
            raw = headers
        lowered = raw.lower()
        if "list-unsubscribe" in lowered:
            return True
        for marker in _AUTO_REPLY_HEADERS:
            if marker in lowered:
                return True
        return False


def _extract_email(value: str) -> str:
    match = _EMAIL_RE.search(value or "")
    return match.group(0) if match else ""


def _prepend_re(subject: str) -> str:
    if re.match(r"^\s*re\s*:", subject, flags=re.IGNORECASE):
        return subject
    return f"Re: {subject}"
