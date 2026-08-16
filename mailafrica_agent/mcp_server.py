from __future__ import annotations

import warnings
from contextlib import asynccontextmanager
from typing import Any

# The mcp SDK declares FastMCP.lifespan with an unresolved forward reference,
# which Pydantic flags once on construction. Harmless; silence just that.
warnings.filterwarnings(
    "ignore",
    message="Field 'lifespan' has an incomplete definition",
    category=Warning,
)

from mcp.server.fastmcp import FastMCP

from .agent import Agent
from .config import Settings
from .mailafrica import MailAfricaClient
from .ngamia import NgamiaClient
from .store import Store

MODES = ("auto", "draft", "off")


class Runtime:
    """Shared component container for both the MCP server and the webhook app."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.mail = MailAfricaClient(settings.mailafrica_api_base, settings.mailafrica_api_key)
        self.ngamia = NgamiaClient(settings.ngamia_base_url, settings.ngamia_api_key, settings.ngamia_model)
        self.store = Store(str(settings.db_path))
        self.agent = Agent(settings, self.mail, self.ngamia, self.store)
        self._connected = False

    async def connect(self) -> None:
        await self.store.connect()
        self._connected = True

    async def aclose(self) -> None:
        if self._connected:
            await self.store.close()
        await self.mail.aclose()
        await self.ngamia.aclose()


def build_server(runtime: Runtime) -> FastMCP:
    @asynccontextmanager
    async def lifespan(_: FastMCP):
        await runtime.connect()
        try:
            yield {}
        finally:
            await runtime.aclose()

    mcp = FastMCP("mailafrica-agent", lifespan=lifespan)
    mail = runtime.mail
    ngamia = runtime.ngamia
    agent = runtime.agent

    # ---- outbound ----------------------------------------------------------

    @mcp.tool()
    async def send_email(
        to: list[str],
        subject: str,
        text_body: str = "",
        html_body: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        from_domain_id: int | None = None,
        from_address: str | None = None,
    ) -> dict[str, Any]:
        """Send an email through MailAfrica. With from_domain_id/from_address
        the mail goes out from a verified sending domain; otherwise the
        platform sender is used."""
        return await mail.send_email(
            to=to,
            subject=subject,
            text_body=text_body or None,
            html_body=html_body or None,
            cc=cc,
            bcc=bcc,
            from_domain_id=from_domain_id,
            from_address=from_address,
        )

    @mcp.tool()
    async def list_outbound_emails(limit: int = 20) -> list[dict[str, Any]]:
        """List recent outbound emails sent through MailAfrica."""
        return await mail.list_outbound(limit)

    @mcp.tool()
    async def get_outbound_email(message_id: int) -> dict[str, Any]:
        """Fetch a single outbound email by its message id."""
        return await mail.get_outbound(message_id)

    # ---- inbound -----------------------------------------------------------

    @mcp.tool()
    async def list_inbound_addresses() -> list[dict[str, Any]]:
        """List the account's inbound (receiving) email addresses."""
        return await mail.list_addresses()

    @mcp.tool()
    async def create_inbound_address(local_part: str, label: str = "") -> dict[str, Any]:
        """Create a new inbound address (e.g. local_part@yourdomain.com or
        local_part@mailafrica.online). Mail sent there is parsed and delivered
        to webhooks."""
        return await mail.create_address(local_part, label or None)

    @mcp.tool()
    async def delete_inbound_address(address_id: int) -> dict[str, Any]:
        """Delete an inbound address; mail to it stops being received."""
        return await mail.delete_address(address_id)

    @mcp.tool()
    async def list_inbound_messages(
        address_id: int, unread: bool = False, limit: int = 20
    ) -> list[dict[str, Any]]:
        """List inbound messages received at an address."""
        return await mail.list_messages(address_id, unread=unread, limit=limit)

    @mcp.tool()
    async def get_inbound_message(message_id: int) -> dict[str, Any]:
        """Fetch a full inbound message (from, subject, body, headers)."""
        return await mail.get_message(message_id)

    # ---- sending domains ---------------------------------------------------

    @mcp.tool()
    async def list_sending_domains() -> list[dict[str, Any]]:
        """List sending domains and their status/DNS records."""
        return await mail.list_sending_domains()

    @mcp.tool()
    async def add_sending_domain(domain: str) -> dict[str, Any]:
        """Register a sending domain; returns the DKIM/CNAME records to publish."""
        return await mail.add_sending_domain(domain)

    @mcp.tool()
    async def verify_sending_domain(domain_id: int) -> dict[str, Any]:
        """Re-check a sending domain's DNS records with ZeptoMail."""
        return await mail.verify_sending_domain(domain_id)

    # ---- webhooks ----------------------------------------------------------

    @mcp.tool()
    async def list_webhooks(address_id: int) -> list[dict[str, Any]]:
        """List the webhooks wired to an inbound address."""
        return await mail.list_webhooks(address_id)

    @mcp.tool()
    async def create_webhook(address_id: int, url: str, secret: str = "") -> dict[str, Any]:
        """Create a webhook for an inbound address. MailAfrica POSTs delivery
        notifications there (signed with the secret in X-Signature)."""
        return await mail.create_webhook(address_id, url, secret or None)

    @mcp.tool()
    async def delete_webhook(webhook_id: int) -> dict[str, Any]:
        """Delete a webhook."""
        return await mail.delete_webhook(webhook_id)

    @mcp.tool()
    async def test_webhook(webhook_id: int) -> dict[str, Any]:
        """Ask MailAfrica to deliver a test ping to a webhook URL."""
        return await mail.test_webhook(webhook_id)

    # ---- billing -----------------------------------------------------------

    @mcp.tool()
    async def wallet_balance() -> dict[str, Any]:
        """Current TZS wallet balance."""
        return await mail.balance()

    # ---- agent -------------------------------------------------------------

    @mcp.tool()
    async def agent_config(
        address_id: int,
        mode: str | None = None,
        persona: str | None = None,
        reply_from_domain_id: int | None = None,
        reply_from_address: str | None = None,
    ) -> dict[str, Any]:
        """Configure auto-reply for an inbound address. mode is 'auto' (send
        replies), 'draft' (produce but don't send), or 'off'. persona overrides
        the default system prompt. reply_from_domain_id/reply_from_address
        choose the From address replies are sent from. Saved to MailAfrica (the
        source of truth shared with the web app)."""
        if mode is not None and mode not in MODES:
            return {"error": f"mode must be one of {MODES}"}
        kwargs = {k: v for k, v in {
            "mode": mode,
            "persona": persona,
            "reply_from_domain_id": reply_from_domain_id,
            "reply_from_address": reply_from_address,
        }.items() if v is not None}
        return await mail.set_agent_config(address_id, **kwargs)

    @mcp.tool()
    async def agent_get_config(address_id: int) -> dict[str, Any]:
        """Fetch the current auto-reply config for an inbound address."""
        cfg = await mail.get_agent_config(address_id)
        return cfg or {"address_id": address_id, "mode": "off", "enabled": True}

    @mcp.tool()
    async def agent_status() -> dict[str, Any]:
        """Which addresses have auto-reply configured and their modes."""
        cfgs = await mail.list_agent_configs()
        return {"addresses": cfgs}

    @mcp.tool()
    async def agent_draft(address_id: int, subject: str, text_body: str) -> dict[str, Any]:
        """Generate a one-off auto-reply preview via MailAfrica (never sends)."""
        return {"draft": await mail.draft_reply(address_id, subject, text_body)}

    @mcp.tool()
    async def agent_handle_message(message_id: int, address_id: int) -> dict[str, Any]:
        """Run the auto-reply pipeline for an inbound message now (respects the
        address's configured mode)."""
        return await agent.handle_message(message_id, address_id)

    @mcp.tool()
    async def list_models() -> list[str]:
        """List the models available on the Ngamia gateway."""
        return await ngamia.list_models()

    return mcp
