# Architecture

The Universal Provider Router is a zero-dependency-forward HTTP proxy that
accepts requests in two LLM API dialects and forwards them to any number of
OpenAI-compatible upstream providers.

## Dual-intake design

A single `http.createServer` dispatches on method + path
(`router/src/index.ts`):

| Route | Dialect | Typical client |
|-------|---------|----------------|
| `POST /v1/messages` | Anthropic Messages API | Claude Code |
| `POST /v1/chat/completions` | OpenAI Chat Completions | OpenCode, Hermes |
| `POST /v1/messages/count_tokens` | Anthropic (token estimate stub) | Claude Code |
| `GET /v1/models` | OpenAI model listing | any |
| `GET /health` | health/status | any |
| `GET /usage` | usage summary | any |

The **OpenAI intake** forwards requests largely as-is (pass-through), only
rewriting the `model` field after provider resolution. The **Anthropic intake**
translates the request to OpenAI format, forwards it, and translates the
response (or stream) back to Anthropic format before returning it to the
client.

## Provider resolution

`resolveProvider(model)` in `router/src/index.ts` decides where a request goes:

1. **Prefix match** — a model like `litellm/qwopus3.5` splits on the first `/`;
   if the prefix names a configured provider, route there with the remainder as
   the upstream model id.
2. **Model map** — for `claude-*` wire names, each provider's `model_map` is
   checked. The mapped value is normally the exact upstream model id; a leading
   `prefix/` is stripped only when that prefix is itself a configured provider
   (legacy routing style), so aggregator catalogs that use `org/model` ids reach
   upstream verbatim.
3. **Active provider** — fall back to `active_provider` from config.
4. **First provider** — last resort.

Provider definitions and defaults come from `router/src/middleware/router-config.ts`.

## Catalog (model truth)

The invariant: **a provider's valid model list is whatever its live `/models`
endpoint reports** — never a hand-maintained list.

- **`GET /v1/models` (proxy)** mirrors the upstream listing
  (`src/utils/upstream-catalog.ts`): each provider's ids are fetched, cached per
  TTL, and served verbatim + provider-namespaced, plus the `model_map` wire
  names the proxy actually maps. On an upstream fetch failure the last good
  cache is served (stale-while-error); with no cache at all it falls back to the
  configured list.
- **TTL**: tailnet-local endpoints (hot-swapping lanes) use `0` — always fresh;
  remote endpoints cache briefly (`CATALOG_TTL_S` in the CLI, mirrored as
  `UPB_CATALOG_TTL` at proxy launch). A retired model disappears within one TTL.
- **Run-time validation**: `upb run provider/<model>` and `upb default`
  validation both hit `/models` live; a stale cache is an acceptable fallback
  only while `/models` is briefly unreachable.
- **`catalog: static`** is the deprecated opt-out for endpoints that serve no
  listing — they hand-maintain `models:` and own their pin hygiene.
- **Anthropic-native** endpoints (no OpenAI `/models` at the serving base) are
  live only when `models_base_url` points at a real listing (e.g. z.ai paas/v4);
  otherwise they stay static.
- **`models:` is pricing metadata only** — it never gates validity. The CLI
  forwards it as `UPB_PRICING` so `cost_usd` works for dynamic routes.
- **Wire pins** (`ANTHROPIC_*`) derive from the run's model, overridable per
  tier via `opus_model`/`sonnet_model`/`haiku_model`. `upb verify` audits every
  pin against the live catalog: a pin naming a retired id is a hard finding
  (exit 3), and `upb run` refuses to launch with it.

## Configuration

`router-config.ts` loads config in priority order:

1. **Env-var mode** — if `UPB_PROVIDER` or `UPB_BASE_URL` is set, build a
   single-provider config from `UPB_*` env vars (no YAML needed). Launchers and
   the systemd service use this to pin one provider+model per instance.
2. **YAML discovery** — otherwise search `UPB_CONFIG`,
   `~/.config/universal-router/providers.yaml`, `./providers.yaml`, and
   `../../providers.yaml`. `${ENV_VAR:-default}` placeholders in the YAML are
   resolved against the process environment at load time, so API keys never live
   in the file.

## Translation layer

`router/src/utils/translate.ts` converts between the two dialects:

- `translateRequest` — Anthropic Messages → OpenAI Chat Completions (messages,
  system prompt, tools, tool_choice, sampling params).
- `translateResponse` — OpenAI non-streaming response → Anthropic response.
- `translateError` — OpenAI error shape → Anthropic error shape.
- `estimateTokenCount` — backs the `/v1/messages/count_tokens` stub.

Adapters (`router/src/adapters/`) add per-provider behavior: whether to strip
`thinking` blocks, strip `cache_control`, request timeout, and extra headers.

## Streaming pipeline

Claude Code always streams, so this is the critical path
(`router/src/utils/stream.ts`):

- `AnthropicStreamTransformer` is a `Transform` stream that consumes OpenAI SSE
  chunks and emits Anthropic SSE events (`message_start`, `content_block_delta`,
  `message_delta`, `message_stop`, etc.). It reassembles streamed tool-call
  argument fragments into complete tool-use blocks.
- `createKeepaliveStream` wraps the transformer to emit periodic keep-alive
  events so long-running generations don't trip client-side idle timeouts.

For OpenAI-intake streaming, provider SSE is piped straight through to the
client without translation.

## Auth model

`router/src/middleware/auth.ts` validates the Anthropic intake against a shared
`LOCAL_SECRET` (env var, or the `defaults.local_secret` config value). The key
may arrive as `x-api-key` or `Authorization: Bearer`. The OpenAI intake does not
enforce this check. This is a localhost trust boundary, not a substitute for
network-level protection.

## Retry logic

`router/src/utils/errors.ts` classifies failures:

- **Retryable** — network errors, timeouts, `429`, `408`, and `5xx`.
- **Non-retryable** — `400`, `401`, `403` (client errors won't fix themselves).

`forwardToProvider` in `index.ts` retries retryable failures up to
`defaults.retries` times with exponential backoff plus jitter
(`getRetryDelay`), then surfaces the last error in the client's expected dialect.

## Usage logging

`router/src/utils/usage-logger.ts` appends one JSONL line per request to
`usage.jsonl` (override with `USAGE_LOG`), capturing provider, model, wire
model, token counts, and stream flag. Usage is extracted from non-streaming
response bodies (`extractUsage`) or from SSE chunks
(`extractUsageFromSSE`, which requests `stream_options.include_usage`). The
`/usage` endpoint aggregates this log into totals by provider and by model.

## Source map

| File | Responsibility |
|------|----------------|
| `src/index.ts` | HTTP server, routing, intake handlers, forwarder |
| `src/middleware/router-config.ts` | Config loading (env + YAML), provider definitions |
| `src/middleware/auth.ts` | Shared-secret auth for the Anthropic intake |
| `src/middleware/config.ts` | Provider config types used by the translate layer |
| `src/utils/translate.ts` | Anthropic ↔ OpenAI request/response/error translation |
| `src/utils/stream.ts` | OpenAI → Anthropic SSE stream transformer + keep-alive |
| `src/utils/errors.ts` | Error classification and retry/backoff policy |
| `src/utils/usage-logger.ts` | JSONL usage logging and extraction |
| `src/adapters/registry.ts`, `src/adapters/types.ts` | Per-provider adapter behavior |
| `src/types/` | Shared TypeScript types for both API dialects |
