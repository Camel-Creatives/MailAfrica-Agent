# MailAfrica Agent

Email agentic power for [MailAfrica](https://mailafrica.online): an MCP server
that exposes the MailAfrica API as tools to any AI agent, plus a webhook-driven
**auto-reply agent** that answers inbound email conversationally using the
[Ngamia](https://docs.ngamia.cc) OpenAI-compatible gateway.

```
Incoming email ─► MailAfrica inbound ─► webhook ─► agent ─► Ngamia ─► reply
  (support@brand.com)   (parse)            │         │        │          │
                                           │   thread memory  │    via MailAfrica
                                           │   (SQLite)       │    outbound API
                                           └───────────────────┘
```

## Components

- **MCP server** (`mailafrica-agent mcp`, stdio) — tools for outbound send,
  inbound addresses/messages, sending domains, webhooks, wallet balance, and
  auto-reply configuration. Works in Claude Desktop/Code, Cursor, or any MCP
  client.
- **Webhook server** (`mailafrica-agent webhook`) — FastAPI endpoint that
  receives MailAfrica delivery notifications (HMAC-verified), runs the agent
  in the background, and sends the reply.
- **Auto-reply agent** — per-address personas and modes (`auto` / `draft` /
  `off`), conversation memory keyed by (sender, subject) thread, and safety
  guards: never replies to bounces, auto-responders, or bulk mail, and never
  leaks keys or prompts.

## Setup

```bash
cp .env.example .env   # fill in MAILAFRICA_API_KEY and NGAMIA_API_KEY
uv sync
uv run mailafrica-agent check   # validates config + connectivity
```

Run the webhook server and point a MailAfrica webhook at it:

```bash
uv run mailafrica-agent webhook            # default 0.0.0.0:8000
```

Create a webhook for an inbound address (via the dashboard or MCP):
`POST /webhooks/mailafrica` — with `AGENT_WEBHOOK_SECRET` set, MailAfrica's
`X-Signature` (HMAC-SHA256 of the body) is verified before processing.

## Using it as an MCP server

```bash
uv run mailafrica-agent mcp
```

Register in Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mailafrica-agent": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/MailAfrica-Agent", "mailafrica-agent", "mcp"]
    }
  }
}
```

Enable auto-reply on an address, e.g. ask the agent:

> Configure auto-reply on address 12 in `auto` mode, replying from
> `noreply@ziadapos.com` (domain id 23), with a persona that handles
> Tanzanian customers in Swahili or English.

## Safety

- Auto-reply is **off by default** per address; turn it on explicitly.
- Draft mode produces a reply without sending it.
- The webhook HMAC secret is required to trust delivery notifications.
- Reply-from requires a verified sending domain (and a registered sender
  address for non-default local parts).
