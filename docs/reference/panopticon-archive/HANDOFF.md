# HANDOFF — Panopticon

**Session date:** 2026-07-21
**Project path:** `/Users/fabiofalopes/projetos/hub/panopticon`
**Formerly:** `local-litellm`

---

## What This Project Is

A personal LLM control plane. All AI traffic (Fabric, scripts, agents, OpenCode) routes through one gateway. Every token, prompt, and cost is tracked. OAuth subscriptions (ChatGPT Plus, Claude Pro, etc.) can be bridged via CLIProxyAPI.

## Architecture (6 Docker services)

```
Tools → LiteLLM (:4000) → [Direct providers, CLIProxyAPI (:8317)]
         │                    │
         ├→ Redis (cache)     └→ OAuth subscriptions (ChatGPT/Claude/Gemini/Grok)
         ├→ Postgres (spend)
         └→ Langfuse (:3000, traces)
```

| Service | Port | Credentials |
|---|---|---|
| LiteLLM proxy | `:4000` | Master key: `sk-local-litellm` |
| Langfuse UI | `:3000` | `admin@local.dev` / `admin1234` |
| CLIProxyAPI panel | `127.0.0.1:8317/management.html` | `cliproxy-mgmt-local` |
| CLIProxyAPI API | `:8317` (internal) | `sk-cliproxy-internal` |
| Postgres (LiteLLM) | internal | `litellm` / `litellm-pw` |
| Postgres (Langfuse) | internal | `langfuse` / `langfuse-pw` |
| Redis | internal | No auth |

## Secrets (stored in `~/.secrets.age` via `secrets` tool)

| Secret name | Env var | Used by |
|---|---|---|
| `MODELOS_AI_KEY` | `MODELOS_AI_KEY_API_KEY` | LiteLLM → modelos.ai.ulusofona.pt |
| `ALIBABA_TOKEN_PLAN_KEY` | `ALIBABA_TOKEN_PLAN_KEY_API_KEY` | LiteLLM → Alibaba Token Plan + CLIProxyAPI |
| `LANGFUSE_PUBLIC_KEY` | `LANGFUSE_PUBLIC_KEY_API_KEY` | LiteLLM → Langfuse callback |
| `LANGFUSE_SECRET_KEY` | `LANGFUSE_SECRET_KEY_API_KEY` | LiteLLM → Langfuse callback |
| `ZEN_API_KEY` | `ZEN_API_KEY_API_KEY` | LiteLLM → OpenCode Zen free models |

## File Map

| File | Purpose | Generated? |
|---|---|---|
| `docker-compose.yml` | 6 services, ports, volumes, depends_on | No |
| `config.yaml` | LiteLLM models (10 active), Langfuse callback, Redis cache | No |
| `cliproxy-config.tmpl.yaml` | CLIProxyAPI template (Alibaba provider, OAuth instructions) | No |
| `cliproxy-config.yaml` | CLIProxyAPI runtime config (key substituted) | Yes — by `start.sh` |
| `start.sh` | Secret checks, generates `.env` + `cliproxy-config.yaml`, starts stack | No |
| `.env` | API keys (mode 600) | Yes — by `start.sh` |
| `cliproxy-auths/` | OAuth token storage (populated by `docker exec --auth`) | No (empty) |
| `cliproxy-logs/` | CLIProxyAPI rotating logs | No (auto) |
| `custom_hooks.py` | Message format fix for Qwen3 (deferred, not active) | No |
| `README.md` | Full documentation | No |

## Active Models (15 in LiteLLM)

| Model name | Routes through | Provider | Spend tracked? |
|---|---|---|---|
| `amalia-9b` | Direct | modelos.ai.ulusofona.pt | No (no pricing data) |
| `omnicoder-9b` | Direct | modelos.ai.ulusofona.pt | No (no pricing data) |
| `ornith-9b` | Direct | modelos.ai.ulusofona.pt | No (no pricing data) |
| `qwen3.8-max-preview` | Direct | Alibaba Token Plan | Yes (trial estimate) |
| `qwen3.7-plus` | Direct | Alibaba Token Plan | Yes ($0.32/$1.28 per 1M) |
| `qwen3.7-max` | Direct | Alibaba Token Plan | Yes ($2.50/$7.50 per 1M list) |
| `qwen3.6-flash` | Direct | Alibaba Token Plan | Yes ($0.26/$1.56 per 1M) |
| `deepseek-v4-pro` | Direct | Alibaba Token Plan | Yes ($2.50/$5.00 per 1M) |
| `glm-5.2` | Direct | Alibaba Token Plan | Yes ($1.46/$4.58 per 1M) |
| `glm-5.2-via-cliproxy` | CLIProxyAPI | Alibaba Token Plan | Yes (same as glm-5.2) |
| `big-pickle` | Direct | OpenCode Zen (free) | $0 (free) |
| `deepseek-v4-flash-free` | Direct | OpenCode Zen (free) | $0 (free) |
| `mimo-v2.5-free` | Direct | OpenCode Zen (free) | $0 (free) |
| `north-mini-code-free` | Direct | OpenCode Zen (free) | $0 (free) |
| `nemotron-3-ultra-free` | Direct | OpenCode Zen (free) | $0 (free) |

CLIProxyAPI also has 6 models with `-cliproxy` suffix (internal, for LiteLLM routing).

**Zen model corrections** (vs previous HANDOFF):
- `nemotron-3-super-free` → renamed to `nemotron-3-ultra-free` in production
- `minimax-m2.5-free` → NOT in current Zen docs (commented out in config)
- `hy3-free` → NOT found anywhere (commented out in config)
- Zen requires API key (NOT no-auth) — stored as `ZEN_API_KEY` in secrets
- Zen free models are rate-limited (~11h cooldown when exceeded)
- Zen free models may use data for training — no sensitive data

## Key Decisions This Session

### Session 2026-07-20
1. **Added Alibaba Token Plan** (6 models: Qwen, DeepSeek, GLM) via OpenAI-compatible endpoint
2. **Added CLIProxyAPI as backend** behind LiteLLM (not a replacement) — hybrid architecture
3. **CLIProxyAPI port bound to `127.0.0.1` only** — not reachable from LAN (security)
4. **CLIProxyAPI management `allow-remote: true`** — safe because port is localhost-only
5. **Alibaba key in CLIProxyAPI via template + start.sh substitution** — CLIProxyAPI doesn't support env vars in config, so `start.sh` substitutes `__ALIBABA_KEY__` from secrets
6. **Test model `glm-5.2-via-cliproxy`** — proves the LiteLLM → CLIProxyAPI → Alibaba chain works end-to-end (28 tokens tracked in both LiteLLM SpendLogs and CLIProxyAPI usage queue)
7. **Spend is $0 for custom model names** — LiteLLM doesn't have pricing for `glm-5.2-cliproxy`; needs `model_info` with `input_cost_per_token` / `output_cost_per_token` to track real spend
8. **IPv6 issue** — `localhost` resolves to `::1` first, Docker binds to `127.0.0.1` only; use `127.0.0.1` for CLIProxyAPI

### Session 2026-07-21
9. **Added 5 OpenCode Zen free models** — big-pickle, deepseek-v4-flash-free, mimo-v2.5-free, north-mini-code-free, nemotron-3-ultra-free. Endpoint: `https://opencode.ai/zen/v1`. API key required (extracted from OpenCode auth.json → stored as `ZEN_API_KEY` in secrets).
10. **Added `model_info` pricing to all Alibaba models** — Spend tracking now shows real USD. Pricing based on International (ap-southeast-1) rates. qwen3.7-max has 50% promo active, qwen3.7-plus has 20% promo. qwen3.8-max-preview is 10% trial (estimate).
11. **DeepSeek/GLM via DashScope is expensive** — deepseek-v4-pro costs $2.50/$5.00 per 1M on DashScope vs $0.44/$0.87 on DeepSeek's own API (4-6× markup). glm-5.2 is similar. Consider direct API keys for cost savings.
12. **Compose project name fixed** — migrated from `local-litellm` to `panopticon`. `docker compose` commands now work without `-p` flag.
13. **OpenCode routing research done** — best approach is adding `litellm` as custom provider in opencode.json (like lmstudio/ollama), NOT replacing built-in providers. OmO overrides completely replace global model. See P2 below.

## What Was Verified Working

- LiteLLM routes to 15 models (3 ULusofona + 6 Alibaba + 5 Zen free + 1 CLIProxyAPI test)
- CLIProxyAPI has 6 models from Alibaba `openai-compatibility` provider
- Test call `glm-5.2-via-cliproxy` → 28 tokens → tracked in LiteLLM SpendLogs + CLIProxyAPI usage queue + Langfuse trace
- CLIProxyAPI management panel at `http://127.0.0.1:8317/management.html`
- Langfuse callback initialized (`Initialized Success Callbacks - ['langfuse']`)
- **Zen free models route correctly** — big-pickle (111 tokens), deepseek-v4-flash-free (141 tokens), north-mini-code-free (58 tokens) all tracked
- **Spend tracking shows real dollars** — qwen3.6-flash call: $0.004 (was $0 before model_info)
- **Zen API key extracted from OpenCode auth.json** and stored in secrets as `ZEN_API_KEY`

## Next Steps (Prioritized)

### ~~P1: Map OpenCode Zen (free models) through the stack~~ ✅ DONE
- 5 Zen free models added: big-pickle, deepseek-v4-flash-free, mimo-v2.5-free, north-mini-code-free, nemotron-3-ultra-free
- Endpoint: `https://opencode.ai/zen/v1`, API key stored as `ZEN_API_KEY`
- minimax-m2.5-free and hy3-free commented out (not in current Zen docs)

### P2: Plug OpenCode to use this stack (RESEARCH DONE — needs user decision)
- **Best approach**: Add `litellm` as a custom provider in `opencode.json` (same pattern as lmstudio/ollama)
- Add `"litellm/"` to `KNOWN_PREFIXES` in `scripts/set-model.ts`
- Wire into OmO tier configs as terminal fallback (after paid providers fail)
- **DO NOT** replace built-in providers (`opencode-go/`, `opencode/`, `zai-coding-plan/`) — they're resolved by OpenCode's internal auth system, can't be redirected
- **Decision needed**: Should LiteLLM be a fallback (safe) or primary route (risky)? Which agents?

### P3: Evaluate CLIProxyAPI stability
- CLIProxyAPI is experimental — single maintainer, ToS gray area, documented account bans
- Monitor for issues over the next few weeks
- If unstable: remove CLIProxyAPI, keep LiteLLM direct routing only
- If stable: add OAuth subscriptions (Claude, ChatGPT, Gemini) for cost arbitrage

### ~~P4: Add custom pricing for CLIProxyAPI-routed models~~ ✅ DONE
- `model_info` blocks added to all 6 Alibaba models + glm-5.2-via-cliproxy
- Pricing based on International (ap-southeast-1) USD rates
- Active promos noted: qwen3.7-max 50% off, qwen3.7-plus 20% off, qwen3.8-max-preview 10% trial
- **Note**: DeepSeek/GLM via DashScope is 4-6× more expensive than their direct APIs

### P5: Consider monitoring vs rerouting for XAMPP
- XAMPP has its own API built into the binary
- May be more interested in monitoring (traces, spend) than rerouting
- Could add XAMPP as a provider in LiteLLM for tracking only
- Or could route XAMPP traffic through LiteLLM for unified accounting

### P6: Keep mapping all provider subscriptions
- User has multiple provider subscriptions (gas/providing)
- Keep adding them to this stack for unified tracking
- Each new provider: add to config.yaml (direct) or cliproxy-config.tmpl.yaml (OAuth)
- **Available secrets not yet mapped**: ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, MISTRAL_API_KEY, OPENAI_API_KEY, XAI_API_KEY

### ~~P7: Fix compose project name~~ ✅ DONE
- Migrated from `local-litellm` to `panopticon` project name
- Added `name: panopticon` to docker-compose.yml
- `docker compose` commands now work without `-p` flag

### P8: Update pricing when promos end
- qwen3.7-max: 50% promo → update model_info when it ends ($2.50/$7.50 list)
- qwen3.7-plus: 20% promo → update model_info when it ends
- qwen3.8-max-preview: 10% trial → update when standard pricing published

## Open Questions

1. ~~**Project name**~~ — Resolved: `panopticon`
2. **OpenCode rerouting** — Research done. Best approach: add `litellm` as custom provider + terminal fallback in OmO. **Decision needed**: fallback only, or primary for some agents?
3. **CLIProxyAPI risk tolerance** — is the account ban risk acceptable for cost arbitrage, or should we hold off on OAuth subscriptions?
4. **XAMPP approach** — monitor only, or full rerouting?
5. **Other providers to map** — secrets exist for ANTHROPIC, DEEPSEEK, GEMINI, GROQ, MISTRAL, OPENAI, XAI. Which to add to LiteLLM?
6. **DashScope cost arbitrage** — DeepSeek via DashScope is 4-6× more expensive than DeepSeek's own API ($2.50 vs $0.44 input). Add direct DeepSeek API key to save money?
7. ~~**Compose project name**~~ — Fixed. Now `panopticon`.

## How to Start the Stack

```bash
cd ~/projetos/hub/panopticon
bash start.sh
```

This will:
1. Create `cliproxy-auths/` and `cliproxy-logs/` dirs
2. Verify 5 secrets exist (MODELOS_AI_KEY, ALIBABA_TOKEN_PLAN_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, ZEN_API_KEY)
3. Generate `.env` (mode 600)
4. Generate `cliproxy-config.yaml` from template (mode 600)
5. Start all 6 Docker containers

**Note**: Compose project name is now `panopticon`. Standard `docker compose` commands work.

## Session Management Notes

- Keep prompts tight and accurate for agents
- Don't run long orchestrators — expensive in tokens
- Follow multi-session cadence: plan → execute → handoff → resume
- Each session should end with updated handoff note
- This is a living project — keep restructuring and building
