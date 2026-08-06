# upb — Universal Provider Bridge

Route control + translation proxy for LLM providers. Point Claude Code,
OpenCode, or any OpenAI-compatible client at a single local endpoint and route
requests to whichever provider and model you choose — with protocol
translation, streaming, retries, and usage tracking handled for you.

## The problem

Coding agents are picky about which API they talk to:

- **Claude Code** speaks the Anthropic Messages API and expects `claude-*`
  model names.
- **OpenCode / Hermes / other agents** speak the OpenAI Chat Completions API.

Meanwhile, the models you actually want to use live behind a dozen different
providers, each with its own base URL, auth scheme, and quirks. `upb` collapses
that mess into one local proxy plus one config file.

## Architecture overview

The router is a **dual-intake proxy**:

| Intake | Endpoint | Speaks | Used by |
|--------|----------|--------|---------|
| Anthropic | `POST /v1/messages` | Messages API | Claude Code |
| OpenAI | `POST /v1/chat/completions` | Chat Completions | OpenCode, Hermes, any OpenAI client |

Requests are routed by **model prefix** (`litellm/some-model` → the `litellm`
provider) or by a **model map** that translates `claude-*` wire names to the
real upstream model. Anthropic-format requests are translated to OpenAI format
on the way out and translated back on the way in, including streaming SSE.

```
Claude Code ──/v1/messages──────────┐
                                    ├─▶ [router] ─▶ provider (OpenAI-compatible)
OpenCode ─────/v1/chat/completions──┘      │
                                     translate · retry · log usage
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## Quick start

Requirements: **Node.js 22+**, **Python 3.10+** (with `python3-yaml`).

```bash
# 1. Install the CLI and scaffold config
./scripts/install.sh

# 2. Add your provider keys
$EDITOR ~/.config/upb/secrets.env
chmod 600 ~/.config/upb/secrets.env

# 3. Build and run the router
cd router
npm install
npm run build
npm start
```

The router listens on port `8443` by default (override with `PORT` /
`UPB_PORT`). Check it with:

```bash
curl -s http://localhost:8443/health
```

See [docs/SETUP.md](docs/SETUP.md) for step-by-step instructions, including
running as a systemd service and wiring up Claude Code / OpenCode.

## Route management (the `upb` CLI)

`upb` reads `~/.config/upb/routes.yaml` and manages launching Claude Code (or
any client) through a chosen provider route.

| Command | What it does |
|---------|--------------|
| `upb list [--all] [--json]` | Show eligible routes (or everything with `--all`) |
| `upb models PROVIDER [--refresh]` | List a provider's models (live fetch for `catalog: live`) |
| `upb status [--json]` | Key resolution + live endpoint health |
| `upb run ROUTE [-- ARGS...]` | Launch `claude` through a route (`default`, `provider`, or `provider/model`) |
| `upb stop [ROUTE \| --all]` | Stop proxies spawned by `upb` (never touches systemd's) |
| `upb default` | Show the default route |
| `upb env` | Print shell-exportable env vars pointing at the persistent router |
| `upb sync` | Sync keys: pull from source stores → `secrets.env` → push to derived files |
| `upb doctor` | Check config, keys, ports, binaries, and hygiene |

Exit codes: `0` ok · `2` config/usage error · `3` no eligible route · `4` spawn failed.

## Usage tracking

Every proxied request is appended to a JSONL usage log (`usage.jsonl` in the
working directory by default, override with `USAGE_LOG`). Each entry records
timestamp, provider, model, wire model, prompt/completion/total tokens, and
whether it streamed.

Query a live summary:

```bash
curl -s http://localhost:8443/usage
```

Returns totals plus breakdowns by provider and by model.

## Provider support

Providers are declared in `providers.yaml` (router) and `routes.yaml` (CLI).
All are OpenAI-compatible endpoints unless noted.

| Provider | Kind | Notes |
|----------|------|-------|
| `alibaba` | upb proxy | Alibaba Token Plan; per-model port routing |
| `zai` | anthropic-native | Z.AI coding plan (GLM family) |
| `deepseek` | anthropic-native | Native Anthropic protocol endpoint |
| `zen` | upb proxy | OpenCode Zen free tier |
| `litellm` | upb proxy | LiteLLM gateway (multi-model) |
| `prime-intellect` | upb proxy | Pay-per-use inference, live catalog |
| `ollama` | upb proxy | Local or cloud Ollama |

## Configuration reference

| File | Purpose |
|------|---------|
| `router/providers.yaml` | Router provider definitions, model maps, defaults |
| `~/.config/upb/routes.yaml` | CLI routes, per-provider models/ports, Claude env |
| `~/.config/upb/secrets.env` | Single source of truth for provider keys (`chmod 600`) |
| `config/universal-router.service.example` | systemd user-service template |

Environment variables:

| Variable | Meaning |
|----------|---------|
| `PORT` / `UPB_PORT` | Router listen port (default `8443`) |
| `USAGE_LOG` | Path to the JSONL usage log |
| `LOCAL_SECRET` | Shared secret for the Anthropic intake auth |
| `UPB_ROUTES` | Override path to `routes.yaml` |
| `UPB_SECRETS` | Override path to `secrets.env` |
| `UPB_ROUTER_ENV` | Override path to the router env file used by `upb env`/`upb sync` |
| `UPB_PROVIDER`, `UPB_BASE_URL`, `UPB_API_KEY`, `UPB_MODEL_MAP`, `UPB_TIMEOUT` | Env-var-only router mode (no YAML) |

API keys in `providers.yaml` use `${ENV_VAR:-default}` placeholders so no
secret ever lives in the file itself.

## Repository layout

```
router/    TypeScript dual-intake proxy (src/, package.json, tsconfig.json)
cli/       upb — Python route-control CLI
config/    Example config files (routes, secrets, systemd service)
docs/      Architecture and setup guides
scripts/   install.sh
```

## License

[MIT](LICENSE) — copyright 2026 ken.
