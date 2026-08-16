# Manual Redeploy Guide (MailAfrica-Agent)

The agent runs on the production VPS at `~/projects/mailafrica-agent` and is accessible publicly at `https://agent.mailafrica.online`.

Use this guide when you need to pull recent code changes, update `.env` configuration, or restart the agent service on the server.

---

## 1. Quick Copy-Paste Redeploy (New Code Changes)

Run this one-liner from your local machine to pull the latest code from `main`, rebuild the Docker container, and restart the agent service:

```sh
ssh camel "cd ~/projects/mailafrica-agent && git pull origin main && docker compose up -d --build && curl -s http://localhost:8097/health"
```

Or step-by-step:

```sh
ssh camel
cd ~/projects/mailafrica-agent
git pull origin main
docker compose up -d --build
docker compose ps
curl -s http://localhost:8097/health
```

---

## 2. If You Changed `.env` Variables

If you updated environment variables (e.g. `NGAMIA_API_KEY`, `MAILAFRICA_API_KEY`, `AGENT_WEBHOOK_SECRET`):

```sh
ssh camel
cd ~/projects/mailafrica-agent
nano .env
```

After updating `.env`, apply the changes by rebuilding and recreating the container:

```sh
docker compose up -d --build
curl -s http://localhost:8097/health
```

---

## 3. Health Check & Logs Verification

### Health Check Endpoint
```sh
curl -s https://agent.mailafrica.online/health
# Expected Output: {"status":"ok"}
```

### Viewing Container Logs
```sh
ssh camel "docker compose -f ~/projects/mailafrica-agent/docker-compose.yml logs -f --tail=50"
```

---

## 4. Key Environment Variables Checklist

These variables must be configured in `~/projects/mailafrica-agent/.env`:

| Variable | Value / Description | Example |
|---|---|---|
| `PORT` | Host port mapped to FastAPI | `8097` |
| `NGAMIA_BASE_URL` | Ngamia API gateway URL | `https://api.ngamia.cc/v1` |
| `NGAMIA_API_KEY` | Ngamia LLM API key | `ngm_955a0f6740f...` |
| `NGAMIA_MODEL` | Preferred model ID | `openai/gpt-4o-mini` |
| `MAILAFRICA_API_BASE` | MailAfrica Core API URL | `https://api.mailafrica.online` |
| `MAILAFRICA_API_KEY` | Platform API authentication key | `MAIL_392379010e...` |
| `AGENT_WEBHOOK_SECRET` | HMAC signature secret for inbound webhooks | `local-dev-secret` |
