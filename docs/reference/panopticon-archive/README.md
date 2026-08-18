# Panopticon

Personal LLM control plane — unified endpoint, spend tracking, and full conversation traces. You watch the providers, not the other way around.

## Architecture

```
Fabric / scripts / agents  →  http://localhost:4000 (LiteLLM)
                                ↓
                            ┌──────────┐
                            │  Redis   │  response cache
                            └──────────┘
                                ↓
                            ┌──────────┐
                            │ Postgres │  spend + trace storage
                            └──────────┘
                                ↓                    ┌──────────────────┐
                            ┌──────────────┐         │  CLIProxyAPI      │
                            │ modelos.ai   │         │  (:8317 internal) │
                            │ Alibaba TP   │         │  OAuth bridge     │
                            └──────────────┘         └────────┬─────────┘
                                                              ↓
                                                    ChatGPT / Claude /
                                                    Gemini / Grok subs
                                ↓
                            ┌──────────┐
                            │ Langfuse │  trace UI at :3000
                            └──────────┘
```

LiteLLM is the control plane (keys, spend, traces, cache). CLIProxyAPI is an optional backend that bridges OAuth-based subscription accounts (ChatGPT Plus, Claude Pro, Gemini Advanced, Grok) into OpenAI-compatible API endpoints.

## Services

| Container | Port | Purpose |
|---|---|---|
| `litellm-proxy` | 4000 | OpenAI-compatible gateway. All LLM traffic flows through here. |
| `litellm-db` | (internal) | LiteLLM spend tracking, request logs |
| `langfuse-web` | 3000 | Langfuse UI — conversation traces, dashboards, prompt mgmt |
| `langfuse-db` | (internal) | Langfuse trace storage |
| `litellm-redis` | (internal) | Response cache (identical prompts hit cache, free) |
| `cli-proxy-api` | 8317 (localhost only) | CLIProxyAPI — OAuth subscription bridge + management panel |

## Access Points

| Service | URL | Credentials |
|---|---|---|
| LiteLLM proxy | http://localhost:4000 | `sk-local-litellm` |
| LiteLLM admin UI | http://localhost:4000/ui | Master key `sk-local-litellm` |
| Langfuse UI | http://localhost:3000 | `admin@local.dev` / `admin1234` |
| CLIProxyAPI panel | http://127.0.0.1:8317/management.html | `cliproxy-mgmt-local` |
| LiteLLM models | http://localhost:4000/v1/models | Bearer `sk-local-litellm` |
| LiteLLM spend | http://localhost:4000/global/spend | Bearer `sk-local-litellm` |
| LiteLLM health | http://localhost:4000/health/readiness | — |

## Quick Start

```bash
# 1. Store required secrets (one-time)
secrets prompt MODELOS_AI_KEY
secrets prompt ALIBABA_TOKEN_PLAN_KEY
secrets prompt LANGFUSE_PUBLIC_KEY
secrets prompt LANGFUSE_SECRET_KEY
secrets prompt ZEN_API_KEY

# 2. Start the stack
cd ~/projetos/hub/panopticon
bash start.sh

# 3. Use any OpenAI-compatible tool — point it at localhost:4000
echo "text" | fabric -p ai
pbpaste | txrefine
```

## Adding a New Model

Edit `config.yaml`:

```yaml
model_list:
  - model_name: my-new-model
    litellm_params:
      model: openai/my-new-model
      api_base: https://my-provider.com/v1
      api_key: os.environ/MY_PROVIDER_KEY
```

Then add `MY_PROVIDER_KEY` to your secrets system and to `start.sh`.

## Adding a New Backend (Ollama, OpenRouter, etc.)

```yaml
# Ollama
- model_name: glm-5.2
  litellm_params:
    model: ollama/glm-5.2
    api_base: http://host.docker.internal:11434

# OpenRouter
- model_name: claude-sonnet
  litellm_params:
    model: openrouter/anthropic/claude-sonnet-4
    api_key: os.environ/OPENROUTER_KEY
```

## Adding OAuth Subscriptions via CLIProxyAPI

CLIProxyAPI bridges consumer subscriptions (ChatGPT Plus, Claude Pro, Gemini Advanced, Grok) into OpenAI-compatible API endpoints. It runs as an internal service (`cli-proxy-api:8317`) — not exposed to the host.

### Adding a Subscription

```bash
# Start the stack first (if not running)
bash start.sh

# Run the OAuth flow for the subscription you want to add:
docker exec -it cli-proxy-api ./cli-proxy-api --auth claude    # Claude Pro/Max
docker exec -it cli-proxy-api ./cli-proxy-api --auth codex     # ChatGPT Plus/Pro
docker exec -it cli-proxy-api ./cli-proxy-api --auth gemini    # Gemini Advanced
docker exec -it cli-proxy-api ./cli-proxy-api --auth xai      # Grok
docker exec -it cli-proxy-api ./cli-proxy-api --auth kimi      # Kimi
docker exec -it cli-proxy-api ./cli-proxy-api --auth qwen      # Qwen Code
```

Follow the browser prompt to log in with your subscription account. The OAuth token is stored in `cliproxy-auths/` and auto-refreshed.

### Enabling the Model in LiteLLM

After adding a subscription, uncomment the corresponding model in `config.yaml` under the `# ── CLIProxyAPI` section:

```yaml
- model_name: claude-sonnet-sub
  litellm_params:
    model: openai/claude-sonnet-4-5-20250929
    api_base: http://cli-proxy-api:8317/v1
    api_key: sk-cliproxy-internal
```

Then restart LiteLLM:

```bash
docker compose restart litellm
```

### Checking Available Models

```bash
# List models CLIProxyAPI exposes (after OAuth tokens are added)
curl -s -H "Authorization: Bearer sk-cliproxy-internal" \
  http://localhost:4000/v1/models | jq '.data[].id'
```

### Risk Awareness

OAuth-based subscription bridging operates in a ToS gray area. Providers (Anthropic, Google, OpenAI) may suspend accounts that use third-party OAuth wrappers. Documented ban reports exist for Google Antigravity. Use at your own risk — this is cost arbitrage, not a sanctioned integration.

## File Structure

| File | Purpose |
|---|---|
| `docker-compose.yml` | All 6 services |
| `config.yaml` | Model definitions, Langfuse callback, Redis cache |
| `cliproxy-config.yaml` | CLIProxyAPI config (API keys, routing, OAuth provider templates) |
| `cliproxy-auths/` | OAuth token storage (populated when you add subscriptions) |
| `cliproxy-logs/` | CLIProxyAPI rotating logs |
| `custom_hooks.py` | Pre-built hook for message format fixes (deferred — env var approach used instead) |
| `start.sh` | Generates `.env` from secrets, starts stack |
| `.env` | All API keys (mode 600) |

## Observability

Every LLM call through the proxy captures:

- **Full prompt** sent
- **Full response** received
- **Token counts** (input/output)
- **Latency** breakdown
- **Model + backend** used
- **Cost** calculation
- **Trace ID** for correlation

In Langfuse UI you can:

- View all traces at http://localhost:3000
- Filter by model, time range, or trace name
- See multi-stage pipelines (e.g., `txrefine` shows analyzer + refiner as separate spans)
- Debug why a model failed or was slow
- Track spend per workflow

## Monitoring Commands

```bash
# Global spend
curl -s -H "Authorization: Bearer sk-local-litellm" \
  http://localhost:4000/global/spend

# Per-key spend
curl -s -H "Authorization: Bearer sk-local-litellm" \
  http://localhost:4000/global/spend/keys

# Prometheus metrics
curl -s http://localhost:4000/metrics

# Trace count
docker exec langfuse-db psql -U langfuse -d langfuse \
  -t -c "SELECT count(*) FROM traces;"
```

## Maintenance

```bash
# View logs
docker compose logs -f

# Restart a service
docker compose restart langfuse-web

# Full restart
docker compose down && docker compose up -d

# Wipe everything (DESTRUCTIVE)
docker compose down -v
```

## Key Insight

This stack is your **personal LLM control plane**. Every tool (Fabric, Pydantic AI, LangGraph, custom scripts) connects to the same endpoint. Every token, every prompt, every cost is tracked. You see the full picture.

## Related

- `~/projetos/hub/llm-stack-landscape-2026.md` — research notes on the ecosystem
- `~/.config/fabric/.env` — Fabric config (points at `localhost:4000`)
