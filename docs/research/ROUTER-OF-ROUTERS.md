# Router of Routers — State of the Art + Canonical Registry Design

**Status:** research findings, 2026-10-23. Every URL below was fetched during this
research unless marked `UNVERIFIED`. Claims about the local `upb` and Hermes code
are read from the checked-out source at the commit noted.

**Scope:** the routing layer that sits *above* providers — deciding *which*
model/provider handles a request, and *when* to fall over — for a developer
routing across paid coding subscriptions (Claude Code / Codex / Gemini CLI),
free local models (LM Studio on a Mac), and metered API providers.

---

## 0. Executive summary

1. **Do not route by model ID.** IDs are unstable (providers rename, alias,
   version-stamp). Route by **capability class** resolved at runtime against a
   live catalog.

2. **The canonical registry already exists and is free**: `models.dev`
   (OpenCode project) publishes a **provider-agnostic canonical model layer**
   (`catalog.json` → `models`, 610 canonical models) plus a per-provider map
   with a `canonical_model_id` field on 85.3% of the 8,449 provider-scoped
   model entries. Hermes already consumes `models.dev/api.json`. Do not build
   this from scratch — pin to models.dev and layer your own policy on top.

3. **The state of the art "router of routers" is now shipping inside LiteLLM**
   as the **Auto Router** (`model: auto_router/complexity_router`, tiers
   `SIMPLE/MEDIUM/COMPLEX/REASONING`). It is the closest analogue to what you
   want and the best reference implementation to copy.

4. **Every major agent framework has a fallback-chain concept, but they are
   all raw-ID and all hand-rolled.** Claude Code, Gemini CLI, Hermes, LiteLLM,
   and upb each implement their own chain with different trigger semantics.
   There is no standard.

5. **Runtime model-availability detection is already solved by Claude Code's
   gateway protocol**: `GET /v1/models?limit=1000` against an Anthropic-
   Messages-format gateway. This is the de-facto standard endpoint shape.

6. **Your `upb` project is ~60% of the way to being the router of routers.**
   It already has: dual-intake translation, model_map aliasing, provider
   cooldown/quarantine with alternate-provider failover, and `upb verify`
   (catalog diff + billable 1-token probe). What it lacks is a
   **capability-addressed canonical registry** and **difficulty-aware
   selection**.

---

## 1. Capability-based / semantic routing vs model-ID routing

### 1.1 Why ID-based routing breaks

Observed instability in live catalogs fetched during this research:

| Provider | Evidence |
|---|---|
| OpenRouter | 468 models; **325 have `canonical_slug` ≠ `id`**. E.g. `minimax/minimax-m3.1-flash` → `minimax/minimax-m3.1-flash-20261019`; `deepseek/deepseek-v4.1-flash-1017` → `…-20261017`. **19 entries are aliases** (`alias_target`), e.g. `~openai/gpt-astra-latest` → `openai/gpt-6-astra`. **12 carry `expiration_date`** (e.g. `poolside/laguna-s-2.1` expires 2026-10-31). |
| models.dev | 8,449 provider-scoped models, 230 providers. `canonical_model_id` present on **7,548 (85.3%)**. 475 canonical IDs are shared by >1 provider (the same model resold by Baseten, Ollama Cloud, NVIDIA, Together, etc.). |
| Hermes (local) | `hermes_cli/models_catalog_static.py` carries hardcoded retired-model exclusions — the xAI block explicitly excludes `grok-4*`, `grok-code-fast-1` "Models xAI retired on 2026-05-15" with a doc URL. Codex has a curated list plus "forward-compat synthesis" (`hermes_cli/codex_models.py`). |
| Claude Code | Docs note a gateway "that isn't configured to serve `claude-fable-5-1` rejects requests for that model" — alias resolution depends on the *provider*, not the client. |

So an ID like `claude-sonnet-4-6` means different things at Anthropic vs Bedrock
vs Vertex vs a gateway: Claude Code's own docs tabulate that `sonnet` resolves
to Sonnet 5.5 on the Anthropic API but Sonnet 4.6 on Claude Platform on AWS and
Sonnet 4.5 on Bedrock/Google Cloud.

### 1.2 The fix: capability class + runtime resolution

Instead of `model: "claude-sonnet-4-6"`, address models as
**capability classes**, and resolve the concrete wire ID at request time against
the live catalog:

```
coding.strong     → needs: tool_call=true, context>=200k, reasoning optional
coding.fast       → needs: tool_call=true, context>=32k,  cost<=X
reasoning.deep    → needs: reasoning=true, effort control
vision.any        → needs: attachment=true
local.free        → needs: open_weights=true, cost==0, provider==lmstudio
```

The `upb` router already does the *second half* of this — `model_map` maps
Claude wire names (`claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`)
onto per-provider concrete IDs, including a `model_prefix` mechanism so
OpenCode/Hermes can send `litellm/qwopus3.5-9b-coder` and have it route by
prefix. What it lacks is the *first half*: a class layer above the map.

**Design rule:** classes are stable, IDs are not. Resolve class → provider+ID
at call time, and re-resolve on failure rather than hard-coding.

---

## 2. Difficulty- and cost-aware routers

### 2.1 RouteLLM (lm-sys) — the academic reference

- Paper: https://arxiv.org/abs/2406.18665 (ICLR 2025;
  https://proceedings.iclr.cc/paper_files/paper/2025/file/5503a7c69d48a2f86fc00b3dc09de686-Paper-Conference.pdf)
- Code: https://github.com/lm-sys/RouteLLM
- Blog: https://www.lmsys.org/blog/2024-07-01-routellm/

**Mechanism** (verified in `routellm/controller.py` and
`routellm/routers/routers.py`): a binary router emits `P(strong wins | q)`;
a per-request **cost threshold α** turns that probability into a decision:

```
if calculate_strong_win_rate(prompt) >= threshold:  → strong_model
else:                                              → weak_model
```

**Router variants** (from `routellm/routers/routers.py`, `ROUTER_CLS` registry):
`mf` (matrix factorization — recommended, ~$1.42/1M req), `sw_ranking`
(similarity-weighted Elo), `bert`, `causal_llm`, `random`.

**Threshold calibration** (`config.example.yaml` + `calibrate_threshold.py`):
thresholds are *dataset-specific*, not transferable. Example from the README:
`--routers mf --strong-model-pct 0.5` → threshold `0.11593`. A threshold is
only meaningful relative to the prompt distribution you calibrated on.

**Cost/quality metrics** worth adopting as your router's SLO:
- **PGR** (Performance Gap Recovered): how much of the strong→weak quality gap you closed.
- **APGR**: area under the PGR-vs-cost curve.
- **CPT(x%)** (Call-Performance Threshold): min % of calls to the strong model to hit x% PGR.

**Reported savings**: up to 3.66× cost saving at 95% GPT-4 quality on MT-Bench.
**Router overhead is negligible** ($1.42/1M requests for MF, 155 req/s) versus
LLM generation cost.

**Routing to local models** — directly applicable to you:
https://github.com/lm-sys/RouteLLM/blob/main/examples/routing_to_local_models.md

```python
client = Controller(
  routers=["mf"],
  strong_model="gpt-4-1106-preview",
  weak_model="ollama_chat/llama3",     # ← your LM Studio / local model
)
response = client.chat.completions.create(model="router-mf-0.11593", messages=[...])
```

**Critical limitation for your use case:** RouteLLM is **binary**
(strong vs weak). You have ≥3 heterogeneous pools (subscription CLIs, free
local, metered API). You can run *N* binary routers pairwise, but the
threshold calibration becomes the hard part.

**Limitation #2 (important):** RouteLLM routes *per request*, which for an
agentic coding loop is wrong — it invalidates the KV/prompt cache on every
turn. Not Diamond's own research says single-turn routing is
"brittle and ineffective" for agent sessions because of cache invalidation.
Source: https://notdiamond.ai/blog/interactive-benchmarks-a-new-methodology-for-evaluating-model-routing

### 2.2 Not Diamond

- Docs: https://docs.notdiamond.ai/llms.txt (index; append `.md` for markdown)
- Quickstart: https://docs.notdiamond.ai/docs/quickstart-routing.md

**Mechanism** — a *meta-model* predicts which underlying LLM will give the
best answer for a given prompt. It is a **recommender, not a gateway**: it
returns a choice, you execute the call yourself.

```python
result = client.model_router.select_model(
    messages=[...],
    llm_providers=[
        {"provider": "openai", "model": "gpt-5-2025-08-07"},
        {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
    ],
    tradeoff="cost",   # "cost" | "latency" | None (default = quality)
)
result.provider.model   # the routed model
```

Key API facts: `tradeoff` is the cost/quality dial; `result.session_id` is a
correlation id for the recommendation; `llm_providers` is the candidate set.
Pricing page reportedly lists a routing fee on top of model costs
(`$0.05 per million tokens routed`); the FAQ puts added latency at 100–150 ms.
**UNVERIFIED** — I could not fetch the pricing/FAQ pages (docs site returns
"Page Not Found" for those paths); treat the fee and latency numbers as
vendor-reported.

**Strength for you:** trains custom routers on *your* traffic, and its
**Code** router is explicitly cache-aware and trajectory-aware for agent
sessions (predicts future reward/cost per step, considering KV-cache state).

### 2.3 Martian

- Site: https://martian.ai/ · Docs: https://docs.martian.ai/

Framing: model selection as a **cost-performance optimization** — map the
prompt to the **cheapest model that clears a user-defined quality threshold**.
Closed/interpretability-driven ("Model Mapping"); routing logic is a black box.
Pricing reported as `$20 per 5,000 requests`; savings claims "20–97%" —
**UNVERIFIED** (I could not load docs.martian.ai; empty response). Martian has
pivoted its public surface toward ARES/K-Steering research, with routing as the
older product line — **UNVERIFIED**, based on a secondary comparison page.

### 2.4 LiteLLM Auto Router — the current state of the art (and your closest analogue)

This is the most important finding: **LiteLLM now ships a router-of-routers.**

- Index: https://docs.litellm.ai/docs/auto_router/index.md
- Config reference: https://docs.litellm.ai/docs/proxy/auto_routing.md
- Health-check routing: https://docs.litellm.ai/docs/proxy/health_check_routing.md
- Fallbacks: https://docs.litellm.ai/docs/proxy/reliability.md

**Architecture** (verified from the config reference): one router entry whose
tiers name other models *in the same file*. Four tiers: `SIMPLE`, `MEDIUM`,
`COMPLEX`, `REASONING`.

```yaml
model_list:
  - model_name: claude-haiku-4-5
    litellm_params: {model: anthropic/claude-haiku-4-5, api_key: os.environ/ANTHROPIC_API_KEY}
  - model_name: claude-sonnet-5
    litellm_params: {model: anthropic/claude-sonnet-5, api_key: os.environ/ANTHROPIC_API_KEY}
  - model_name: smart-router
    litellm_params:
      model: auto_router/complexity_router
    complexity_router_config:
      tiers:
        SIMPLE: claude-haiku-4-5
        MEDIUM: claude-sonnet-5
        COMPLEX: claude-sonnet-5
        REASONING: claude-sonnet-5
      classifier_type: heuristic
      complexity_router_default_model: claude-sonnet-5
```

Clients call `model: "smart-router"` — one name, no client change.

**Classifier options** (the "router of routers" decision layer):
| `classifier_type` | What it is | Latency |
|---|---|---|
| `heuristic` (default) | Weighted score over 7 dimensions: tokenCount, codePresence, reasoningMarkers, technicalTerms, simpleIndicators, multiStepPatterns, questionComplexity. Tunable via `tier_boundaries` + `dimension_weights`. | sub-ms, zero API calls |
| `llm` | A small fast model with structured output, routed through the same `Router` (so credentials/budgets/fallbacks apply). | one small call |
| `jev` | TypeSafe System One `POST /v1/systemone` — a `questions.tier` Choice question with the prompt in `state` and tier descriptions in `criteria`. | one call |
| `custom` | Your own async `classify(context)` via `classifier_plugin` (dotted path). | yours |
| keyword rules | `keyword_tier_rules` run *before* the scorer and escalate to the highest matched tier. | sub-ms |

**Agent-relevant knobs worth stealing wholesale:**
- `session_affinity: true` + `session_affinity_ttl_seconds` — pin a session to
  its first-turn model to preserve prompt cache. *This is the fix for RouteLLM's
  cache-invalidation problem.*
- `enable_context_window_escalation` + `context_window_escalation_buffer` (0.95)
  — escalate a prompt that provably doesn't fit the decided tier.
- `adaptive: true` — Thompson-sampling within a tier's pool.
- `classifier_fallback: heuristic | default_model` — classifier failure path.
- `classification_mode: every_request | user_turn` — carry the tier decision
  through continuation turns.
- `return_raw_model_name: true` — return the picked model in the response body
  `model` field instead of restamping the alias.
- `cause=` marker per decision in logs (scorer, literal, semantic, session_pin, LLM, plugin).

**Tiers accept a pool, not just one model** — `SIMPLE: ["gpt-6-luna",
"gemini-3.8-flash"]` is a random-pick pool. That is exactly the mechanism you
need for "cheapest model that passes" across your three pools.

**Modality routing**: for `POST /v1/responses` image requests, LiteLLM checks
`model_info.supports_vision` first, then the loaded model catalog, and returns
an actionable 400 *before* contacting an incompatible provider. It does **not**
probe providers during routing — this is the pattern you want (see §4).

**Published results** (vendor-reported, from the Auto Router index):
| Result | Measured on |
|---|---|
| 74.5% cheaper at 87.3% of frontier quality | RouterArena, 8,399 graded queries |
| Claude Opus-5 solve rate at 27% lower cost | 21-task subset of Terminal-Bench 2.0 |
| 51.1% saved, $12,249 over four months | 272,876 production requests, 450+ users |
| Matched or beat the current model on 88.1% of responses | Shadow eval, 143 judged turns |

### 2.5 Other routers (context, briefly)

- **Not Diamond SimpleClawRouter** (open source, local): weighted regex
  classification over 14 dimensions → tier → model. A good, readable
  reference for a no-dependency heuristic classifier.
  https://github.com/Not-Diamond/SimpleClawRouter
- **RouterArena** (https://routerarena.ai/) — peer-reviewed-ish benchmark for
  LLM routers; LiteLLM publishes against it. The site is a JS SPA; the
  leaderboard is not scrapeable without JS.
- **OracleRouter** (third-party comparison, **UNVERIFIED**):
  https://orcarouter.ai/blog/not-diamond-vs-martian — claims Not Diamond ranks
  12th/12 on RouterArena ("frequently selects expensive models"). Treat as
  vendor-vs-vendor marketing until you read the RouterArena paper.

---

## 3. Failover / fallback-chain and retry semantics

### 3.1 The five different semantics in the wild

| System | Trigger | Scope | Notes |
|---|---|---|---|
| **Claude Code** | "overloaded, unavailable, or returns another non-retryable server error". **Does NOT** trigger on: authentication, billing, rate-limit, request-size, transport errors, or org-policy denial. **DOES** trigger when Bedrock/Google Cloud refuses a model your account can't invoke (treated as unavailable, not auth). | Switch lasts **for the current turn only** — next message tries the primary first again. Chain capped at **3** models after dedup. | `--fallback-model sonnet,haiku` or `"fallbackModel": ["claude-sonnet-5","claude-haiku-4-5"]`. Entries not in `availableModels` are dropped. **Refuses to fall back to a model with a smaller context window than the primary** (would truncate during compaction). Applies to subagents too. |
| **Claude Code (content-based)** | Safety classifier flags (cyber/bio) on Fable/Opus 5.5/Sonnet 5.5/Opus 5. | Category-specific target: Sonnet 5.5 cyber → Sonnet 5; Sonnet 5.5 bio → *refusal, no fallback*. | **After a fallback, the session stays on the fallback model** (unlike availability fallback). |
| **Gemini CLI** | `ModelAvailabilityService` monitors model health. Failure → fallback process; **prompts the user by default**. Internal utility calls (prompt completion, classification) use a **silent** fallback chain: `gemini-2.5-flash-lite` → `gemini-2.5-flash` → `gemini-2.5-pro`. | Current turn or remainder of session, per policy. | Has **Local Model Routing (Experimental)**: a locally-running **Gemma** model makes the routing decisions instead of a hosted model — `gemini gemma` setup command. |
| **Hermes** | `agent/error_classifier.py` — a typed `FailoverReason` enum (see below). Each reason carries recovery hints: `retryable`, `should_compress`, `should_rotate_credential`, `should_fallback`. | Ordered `fallback_providers` chain in `config.yaml`; also a `delegation.fallback_providers` child chain. | **The most sophisticated classifier of the set** — 30+ reason codes. |
| **LiteLLM** | After `num_retries` exhausted → fall back to another model group. `fallbacks = [{"gpt-6-luna": ["gpt-6.1-sol"]}]`. | Router-level. | Plus `cooldown_time`, `allowed_fails_policy` (per-error-class thresholds), and proactive background health checks. |
| **upb (yours)** | 429 → mark provider cooldown (`DEFAULT_COOLDOWN_SECONDS = 300`, per-provider `cooldown_seconds` override) → find an alternate provider serving the same model → else `ProviderQuarantinedError`. | Per-request; provider quarantined for TTL. | `kind: upb` providers can fail over; `kind: anthropic-native` cannot. |

### 3.2 Hermes' `FailoverReason` enum — the best taxonomy found

Read from `/Users/fabiofalopes/.hermes/hermes-agent/agent/error_classifier.py`
(local checkout, commit `be7f7b1af9`). This is the most useful artifact to
copy, because it separates *what to do* from *why it failed*:

```python
class FailoverReason(enum.Enum):
    auth = "auth"                       # 401/403 — refresh/rotate credential
    auth_permanent = "auth_permanent"   # auth failed after refresh — abort
    billing = "billing"                 # 402 / credit exhausted — rotate immediately
    rate_limit = "rate_limit"           # 429 — backoff then rotate
    upstream_rate_limit = "upstream_rate_limit"  # aggregator's upstream 429 — model fallback, key healthy
    upstream_blocked = "upstream_blocked"        # WAF/CDN 403 — key healthy, fallback
    overloaded = "overloaded"           # 503/529
    server_error = "server_error"       # 500/502 — retry
    timeout = "timeout"                 # rebuild client + retry
    ssl_cert_verification = "..."       # deterministic TLS failure — fail fast
    context_overflow = "context_overflow"  # compress, NOT failover
    payload_too_large = "payload_too_large"  # compress payload
    image_too_large / image_corrupt
    model_not_found = "model_not_found"  # 404/invalid model — different model
    provider_policy_blocked = "..."     # aggregator policy excluded endpoint
    content_policy_blocked = "..."      # safety filter — deterministic, don't retry unchanged
    model_entitlement = "model_entitlement"  # account can't use THIS model — rotate credential (model-scoped)
    incomplete_response = "..."         # reasoning-only stall — different provider
    format_error = "format_error"       # 400 — abort or strip + retry
    role_alternation = "..."            # merge same-role msgs for this destination
    invalid_encrypted_content = "..."   # strip replay state
    multimodal_tool_content_unsupported = "..."
    reasoning_mandatory = "..."         # step effort up, don't disable
    thinking_signature / long_context_tier / oauth_long_context_beta_forbidden
    llama_cpp_grammar_pattern = "..."
    unknown = "unknown"                 # retry with backoff
```

Recovery hint bundles used by Hermes (copy this pattern):

```python
_ROTATE_FALLBACK = {"should_rotate_credential": True, "should_fallback": True}
_ABORT_FALLBACK  = {"retryable": False, "should_fallback": True}
_V_MODEL_ENTITLEMENT = _v(_R.model_entitlement, retryable=False, **_ROTATE_FALLBACK)
_V_MODEL_NOT_FOUND   = _v(_R.model_not_found,     **_ABORT_FALLBACK)
_V_CONTEXT_OVERFLOW  = _v(_R.context_overflow, should_compress=True)   # NOT a failover
```

### 3.3 Proposed provider-agnostic fallback policy

**The policy must be expressed in terms of *failure class* and *capability
class*, never model IDs.** A fallback is legal only if the candidate satisfies
the **capability floor** of the request.

```
fallback_policy:
  # Ordering is by preference, not by cost. Each rung may name capability classes.
  chain:
    - class: coding.strong
      provider_pool: [anthropic-subscription, codex-subscription, metered-frontier]
    - class: coding.fast
      provider_pool: [local-lmstudio, free-tier, metered-fast]
    - class: coding.minimal
      provider_pool: [local-lmstudio]

  # Capability floors that a candidate MUST satisfy to be a legal fallback.
  floors:
    tool_call: true          # a coding agent without tools is useless
    context_window: >= 0.95 * request_tokens
    input_modalities: subset_of request
    reasoning: >= request.min_reasoning_effort   # escalate, never de-escalate silently

  # Failure-class → action matrix. Mirrors Hermes' FailoverReason.
  actions:
    rate_limit:        { action: rotate_credential_then_fallback, retry: 2, backoff: exponential+jitter }
    billing:           { action: rotate_credential_then_fallback, retry: 0 }
    auth:              { action: rotate_credential_then_fallback, retry: 0 }
    model_entitlement: { action: rotate_credential_then_fallback, retry: 0 }
    overloaded:        { action: fallback, retry: 2, backoff: exponential+jitter, cooldown: 300 }
    server_error:      { action: retry_then_fallback, retry: 3 }
    timeout:           { action: retry_then_fallback, retry: 1 }
    model_not_found:   { action: fallback, retry: 0 }        # re-resolve class first
    context_overflow:  { action: compress, retry: 0 }        # NOT a fallback
    payload_too_large: { action: compress, retry: 0 }
    content_policy_blocked: { action: abort, retry: 0 }    # deterministic per request
    format_error:      { action: strip_params_and_retry, retry: 1 }
    upstream_blocked:  { action: fallback, retry: 0 }
    unknown:           { action: retry_then_fallback, retry: 2 }

  # Guardrails
  max_fallback_depth: 3        # same as Claude Code's cap
  max_total_attempts: 6
  circuit_breaker:
    failures_before_open: 5
    cooldown_seconds: 300
    half_open_probes: 1
  no_cross_class_degradation: true   # never fall back below coding.minimal
```

**Design notes that matter:**

1. **`model_not_found` must re-resolve, not just switch.** Before falling back,
   re-query the provider's live catalog and re-resolve the capability class. If
   the provider renamed the model, the same class may now be satisfiable at that
   provider with a different ID. This is the single most important rule for
   surviving provider renames.

2. **Subscription-vs-metered distinction is not visible to the HTTP layer.**
   Claude Code's `--fallback-model` triggers on "overloaded or unavailable" but
   **never** on billing/rate-limit — because a subscription has different
   failure semantics than a metered key (a metered 429 is a quota you can
   work around; a subscription 429 means the plan is saturated). Model this
   explicitly: tag each provider pool with `billing_model: subscription |
   metered | free` and let it change the action matrix.

3. **Context-window floor is non-negotiable** for compaction. Claude Code
   refuses to fall back to a smaller-context model for exactly this reason.

4. **Don't retry deterministic failures.** `content_policy_blocked`,
   `context_overflow`, `model_not_found` on a retired ID — retrying unchanged
   just burns budget. This is where Hermes' `retryable=False` earns its keep.

5. **Session pinning beats per-request routing for agents.** Route once per
   *session* (or per task), then stay. LiteLLM's `session_affinity` and
   Gemini CLI's `ModelAvailabilityService` both do this; RouteLLM does not.

---

## 4. Health-check / model-availability discovery

### 4.1 The de-facto standard: `GET /v1/models`

Claude Code's **LLM gateway protocol** is the closest thing to an industry
standard for a router's model-discovery endpoint.

- Source: https://docs.claude.com/en/docs/claude-code/llm-gateway-protocol.md
  (markdown: append `.md`)

**Mechanics (verified from the doc):**
- Request: `GET /v1/models?limit=1000`, **3-second default timeout**
  (`CLAUDE_CODE_GATEWAY_MODEL_DISCOVERY_TIMEOUT_MS` to raise it).
- **Any redirect is treated as failure** — so the credential can't leak to a
  redirect target. Serve `/v1/models` directly at the configured base URL.
- Sends **both** `Authorization` (from `ANTHROPIC_AUTH_TOKEN` or `apiKeyHelper`)
  and `x-api-key` (resolved API key). Sends `ANTHROPIC_CUSTOM_HEADERS` too.
- If neither credential header resolves → discovery is skipped and a
  `[gatewayDiscovery] skipped` line goes to the debug log.
- Enabled by `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`. **Off by default**
  so a shared-key gateway doesn't surface every model the key can access.
- Does **not** run when any `CLAUDE_CODE_USE_*` provider var is set, or when
  `ANTHROPIC_BASE_URL` is unset / points at `api.anthropic.com`.

**Response shape it accepts:**

```json
{
  "data": [
    { "id": "claude-sonnet-4-6",
      "display_name": "Claude Sonnet 4.6",
      "description": "Default model for everyday coding tasks" },
    { "id": "claude-opus-4-8" }
  ]
}
```

**Filtering rules (important):**
- Claude Code keeps an entry only when its `id` contains `claude` **or**
  `anthropic` anywhere (case-insensitive). Provider-prefixed IDs like
  `vertex_ai/claude-sonnet-4-6` or `bedrock/anthropic.claude-sonnet-4-5` pass;
  an ID containing neither is dropped.
- Before v2.1.223 the filter was a *prefix* match, which hid provider-prefixed IDs.
- Discovered entries with no `description` read "From gateway".
- Discovered IDs are deduped against existing picker rows (same ID, or the same
  model as a built-in alias).
- Discovered models must also pass the `availableModels` managed setting.

**This gives you the exact endpoint contract to implement in `upb`:**
`GET /v1/models?limit=1000` → `{"data":[{"id","display_name","description"}]}`.
The `upb` router already has a `/models` surface (`router/src/index.ts` exposes
`model_map` entries) — you need to make it return this exact envelope.

### 4.2 The probe ladder (cheapest → most expensive)

| Probe | Cost | Detects | Notes |
|---|---|---|---|
| **GET `{base_url}/models`** | Free | Renamed/removed model | Standard OpenAI shape: `{"data":[{"id":...}]}`. `upb verify` already does this (`_list_provider_models`, `cli/upb` line ~845). |
| **HEAD `{base_url}/models`** | Free | Endpoint existence | Cheap liveness ping. |
| **GET `{base_url}/models/{id}`** | Free | Single model existence | 404 = gone. Most providers don't implement it; fall back to list-diff. |
| **GET/POST `{base_url}/embeddings`** (embed probe) | Free on local, ~$0.0000x on metered | Model alive + embedding-capable | Cheapest *generative* liveness check on some providers, but **not universal** — not every chat model has an embeddings endpoint. |
| **POST `{base_url}/tokenize`** / `/count_tokens` | Free or near-free | Tokenizer alive, context window | Anthropic has `POST /v1/messages/count_tokens`; Claude Code's gateway protocol lists it as **optional** — if absent, Claude Code falls back to a character-based estimate of context usage. |
| **POST `{base_url}/chat/completions` with `max_tokens:1`** | **Billable** (tiny) | Model actually callable + entitled | This is `upb verify --probe` (`_probe_model`, 1-token chat completion, returns HTTP status). The only probe that catches *entitlement* failures (model exists in the catalog but your key can't use it). |
| **`POST {base_url}/api/show`** | Free | Ollama-native capability probe | Ollama's native endpoint returns `capabilities` including `thinking`. Hermes reads this (`ollama_model_supports_thinking`, `models_local.py` line ~584) because **the OpenAI-compat `/v1/models` omits it**. |
| **`GET {server}/api/v1/models`** | Free | LM Studio loaded+available models | LM Studio's native endpoint (not `/v1/models`). Returns `capabilities` incl. `reasoning.allowed_options` — Hermes reads this (`lmstudio_model_reasoning_options`, line ~565). Also `POST /api/v1/models/load` to load a model on demand (`ensure_lmstudio_model_loaded`, line ~492). |
| **Anthropic `/v1/models`** | Free | Anthropic catalog | Cursor-paginated, default page size — Hermes handles this (`hermes_cli/models.py` line ~842). |

**Live verification note:** my probe of the user's own LM Studio at
`http://localhost:1234/v1/models` returned HTTP 200 with
`{"error":{"message":"An LM Studio API token is required...","code":"invalid_api_key"}}`
— LM Studio is running and reachable, but requires a bearer token. So
**your `/v1/models` probe must send the LM Studio API key**, and treat
`invalid_api_key` as "auth required", not "model list empty".

### 4.3 Proactive vs reactive health checking

LiteLLM's health-check routing is the reference for proactive behavior:

```yaml
general_settings:
  background_health_checks: true
  health_check_interval: 60
  enable_health_check_routing: true
  health_check_ignore_transient_errors: true   # 429/408 never affect routing
  background_health_check_model_groups: ["prod-openai"]   # scope probing
router_settings:
  cooldown_time: 60
  allowed_fails_policy:
    AuthenticationErrorAllowedFails: 1   # cooldown after 2nd auth failure
    TimeoutErrorAllowedFails: 3
```

Request path: **health filter → cooldown filter → (safety net: if all removed,
return all) → load balancer**. Key subtlety: the safety net re-admits broken
deployments rather than failing the request outright.

**Your `upb` router already has the reactive half** (`CooldownRegistry`,
`router/src/utils/cooldown.ts`): mark on 429, `isQuarantined()` check before
routing, `findAlternateProvider()` on quarantine, `ProviderQuarantinedError`
when no alternate exists, and a `/health` snapshot exposing active cooldowns.
**What it lacks:** background polling (so a provider removed upstream is only
discovered on the request that fails), and `ignore_transient_errors` (your
cooldown currently marks on 429 *and* on exhausted retries, but not 408
specifically).

---

## 5. What the agent frameworks actually do (file formats)

### 5.1 Hermes Agent (NousResearch/hermes-agent)

Local checkout: `/Users/fabiofalopes/.hermes/hermes-agent`, remote
`https://github.com/NousResearch/hermes-agent.git`, commit `be7f7b1af9`.

**Verdict: raw IDs everywhere, with a *separate* curated static catalog, plus
a real fallback chain. Aliases exist but are picker-only.**

**Provider declaration** — `hermes_cli/models_catalog_static.py`:

```python
class ProviderEntry(NamedTuple):
    slug: str          # canonical id, e.g. "openai-codex"
    label: str         # human display name
    tui_desc: str      # longer description for the picker

CANONICAL_PROVIDERS: list[ProviderEntry] = [ProviderEntry(*row) for row in (
    ("nous", "Nous Portal", "..."),
    ("openrouter", "OpenRouter", "..."),
    ("lmstudio", "LM Studio", "..."),
    ("anthropic", "Anthropic", "..."),
    ("openai-codex", "ChatGPT or Codex Subscription", "..."),
    ("openai-api", "OpenAI API", "..."),
    ...
)]   # 39 built-in rows, auto-extended by plugins/model-providers/<name>/
```

**Model declaration** — a hardcoded dict `_PROVIDER_MODELS: dict[str, list[str]]`
mapping provider slug → list of raw wire IDs (e.g. `"openai-codex":
_codex_curated_models()`, `"openai": list(_OPENAI_CHAT_MODELS)`). There is also
`OPENROUTER_MODELS: list[tuple[str, str]]` and `VERCEL_AI_GATEWAY_MODELS`.

**Alias mechanism is picker-only** — `hermes_cli/model_search.py`:

```python
_MODEL_SEARCH_ALIASES: dict[str, tuple[str, ...]] = {
    "k3": ("kimi-k3", "kimi"),
    "x-preview-f-free": ("ox-alpha", "ox"),
}
# "Lowercased wire id → extra tokens appended to the search haystack only."
def model_search_text(model): ...   # never changes the wire id sent to the provider
```

So Hermes **does not** have a wire-level alias layer. A `model:` in
`config.yaml` is sent to the provider verbatim.

**Config shape** (`~/.hermes/config.yaml` on this machine):

```yaml
model:
  default: mistral-large-3:675b
  provider: ollama-cloud
  base_url: https://ollama.com/v1
  api_mode: anthropic_messages
fallback_providers: []       # ordered list of {provider, model, ...}
custom_providers:
  - name: Modelos.ai.ulusofona.pt
    base_url: https://modelos.ai.ulusofona.pt/v1
    api_key: "..."
    model: qwopus3.5-9b-coder
    models:                    # discovered model ids
      amalia-9b: {}
      omnicoder-9b: {}
    models_discovered: true
auxiliary:
  vision:   { provider: ..., model: qwen3-vl:235b }
  web_extract: { provider: ..., model: deepseek-v4-pro }
```

Note `auxiliary.*` — Hermes already routes *different model classes* to
different providers (vision vs compression vs title generation). That is a
capability-class router in embryo, expressed as static config rather than a
resolver.

**Fallback chain**: `fallback_providers` is an ordered list of
`{provider, model, base_url?, api_key?|key_env?}`; normalized by
`hermes_cli/fallback_config.py`; the legacy `fallback_model` key is merged in
and dropped on write. `hermes fallback add|remove|list` is the CLI. Delegated
children get their own `delegation.fallback_providers`.

**models.dev integration** — `agent/models_dev.py`:
- `MODELS_DEV_URL = "https://models.dev/api.json"`, cached to
  `~/.hermes/models_dev_cache.json` (with an ETag), with a `models_dev.url`
  mirror override.
- `PROVIDER_TO_MODELS_DEV: Dict[str, str]` maps Hermes slugs → models.dev ids
  (`"openai-codex": "openai"`, `"openai-api": "openai"`, `"gemini": "google"`,
  `"ai-gateway": "vercel"`, `"opencode-zen": "opencode"`, …).
- `ModelInfo` dataclass: `id, name, family, provider_id, reasoning, tool_call,
  attachment, temperature, structured_output, open_weights, input_modalities,
  output_modalities, context_window, max_output, max_input, cost_input,
  cost_output, cost_cache_read, cost_cache_write, knowledge_cutoff,
  release_date, status, interleaved`.
- **Hermes does NOT currently read the `canonical_model_id` field** from
  models.dev. `agent/models_dev.py` never references it (the "canonical"
  strings elsewhere in that file refer to an unrelated "canonical schema" for
  `model_overrides`/`model_capabilities` patches, not to models.dev's
  `canonical_model_id`). Hermes maps **provider→provider**, not
  **model→canonical-model**. That is the exact gap you want to close.
- One adjacent capability Hermes *does* have: `model_switch.py`
  `_configured_provider_matches()` (line ~912) returns
  `{provider_slug: canonical_model_id}` — but its "canonical_model_id" here
  means **the model id as declared in that provider's own config**, not a
  cross-provider canonical id. It routes a *typed* model name to whichever
  configured provider declares it, so a typed name isn't soft-accepted by the
  wrong provider. Useful pattern, different semantics — don't confuse the two.

**Fallback entry shape** (`agent/agent_init.py` `_fallback_entries`, line
~1079): a list of dicts, each requiring `provider` and `model`; optional
`base_url`, `api_key` or `key_env` (also accepted: `api_key_env`). Entries
that resolve no usable credentials are **skipped at init** with a debug log
rather than failing the session.

### 5.2 Claude Code

- Docs: https://docs.claude.com/en/docs/claude-code/model-config.md
- Gateway protocol: https://docs.claude.com/en/docs/claude-code/llm-gateway-protocol.md
- Settings reference: https://docs.claude.com/en/docs/claude-code/settings-reference.md

**Alias-based, not ID-based.** Aliases: `default`, `best`, `fable`, `sonnet`,
`opus`, `haiku`, `opusplan`, plus `[1m]` context variants (`sonnet[1m]`,
`opus[1m]`). The alias resolves differently per provider — Anthropic API
`opus`→Opus 5.5, Bedrock `opus`→Opus 5.5 but `sonnet`→Sonnet 4.5, Foundry
`opus`→Opus 4.6.

**Config files**:
- `~/.claude/settings.json`, `./.claude/settings.json`, `./.claude/settings.local.json`
  (precedence: CLI flags > local > project > user).
- Managed settings (org policy) can restrict with `availableModels`.

**Model picker**:
```json
{
  "fallbackModel": ["claude-sonnet-5", "claude-haiku-4-5"],
  "availableModels": ["claude-opus-5", "claude-sonnet-*"],
  "modelPicker": { "replaceBuiltInOptions": true, "rows": [ ... ] }
}
```

**Gateway discovery** (the key one): `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`
→ `GET {ANTHROPIC_BASE_URL}/v1/models?limit=1000` → `{"data":[{"id","display_name","description"}]}`.

**Custom model entry** (no gateway): `ANTHROPIC_CUSTOM_MODEL_OPTION` +
optional `ANTHROPIC_CUSTOM_MODEL_OPTION_NAME` / `_DESCRIPTION`. Claude Code
**skips validation** on that ID — any string your endpoint accepts works.

**Anthropic-native wire names**: Claude Code only speaks the Anthropic Messages
API and expects `claude-*` names. `ANTHROPIC_BASE_URL` changes *where* requests
go, not *which model* answers.

### 5.3 Codex CLI

- Config reference: https://developers.openai.com/codex/config-reference.md
  (markdown: append `.md`)
- Model catalog: https://raw.githubusercontent.com/openai/codex/main/codex-rs/models-manager/models.json

**TOML** in `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`), with
`config.toml` profiles and a `requirements.toml` for managed/org policy.

```toml
model = "gpt-5.4"
model_provider = "my-proxy"          # provider id from model_providers
model_reasoning_effort = "high"
model_context_window = 400000
model_auto_compact_token_limit = 300000
model_catalog_json = "/path/to/catalog.json"

[model_providers.my-proxy]
name = "My Proxy"
base_url = "http://127.0.0.1:8705/v1"
env_key = "MY_PROXY_KEY"
wire_api = "responses"                # "responses" is the only supported value
model_catalog_url = "https://.../catalog.json"
request_max_retries = 4
stream_max_retries = 5
stream_idle_timeout_ms = 300000
http_headers = { "X-Foo" = "bar" }
query_params = { "api-version" = "2026-01-01" }

[profiles.work]
model = "gpt-5.4"
model_provider = "my-proxy"

[models.new_thread]
model = "gpt-5.4"
model_reasoning_effort = "high"
service_tier = "flex"
```

**Codex-native model catalog** (`codex-rs/models-manager/models.json`): a
`{"models": [...]}` array of ~11 entries, each keyed by `slug` and carrying
**capability flags** rather than raw metadata:

```json
{
  "slug": "gpt-6-astra",
  "display_name": "GPT-6-Astra",
  "description": "Frontier intelligence for the most demanding work.",
  "context_window": 272000,
  "max_context_window": 872000,
  "default_reasoning_level": "low",
  "supported_reasoning_levels": [{"effort":"low","description":"..."}, ...],
  "default_verbosity": "low",
  "support_verbosity": true,
  "apply_patch_tool_type": "freeform",
  "web_search_tool_type": "text_and_image",
  "input_modalities": ["text","image"],
  "supports_image_detail_original": true,
  "supports_parallel_tool_calls": true,
  "tool_mode": "code_mode_only",
  "truncation_policy": {"mode":"tokens","limit":10000},
  "auto_compact_token_limit": null,
  "multi_agent_version": "v2",
  "prefer_websockets": true,
  "use_responses_lite": true
}
```

This is the **best model-list format to imitate for a canonical registry**:
`slug` + capability booleans + limits, with no provider-specific pricing baked in.

Note: `model_providers.<id>.model` is **not** in the config reference — the
model is selected at the top level (`model = "..."`) or per-profile. Provider
ids `openai`, `ollama`, `lmstudio` are **reserved** and cannot be overridden.

### 5.4 OpenCode

- Config: https://opencode.ai/docs/config/ · Providers: https://opencode.ai/docs/providers/

**JSON/JSONC** (`$schema: "https://opencode.ai/config.json"`). Locations, in
precedence order: remote `.well-known/opencode` → global
`~/.config/opencode/opencode.json` → `OPENCODE_CONFIG` env → project
`opencode.json` → `.opencode/` dirs → `OPENCODE_CONFIG_CONTENT` → managed
`/Library/Application Support/opencode/` (macOS) → MDM `.mobileconfig`.

**Provider/model format** — the key file for you:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4-5",
  "provider": {
    "anthropic": {
      "options": { "baseURL": "https://api.anthropic.com/v1" },
      "blacklist": ["claude-opus-4-20250514"],
      "whitelist": ["claude-sonnet-4-20250514"],
      "models": {
        "anthropic-claude-sonnet-4.5": {
          "id": "arn:aws:bedrock:us-east-1:xxx:application-inference-profile/yyy"
        }
      }
    },
    "my-local": {
      "npm": "@ai-sdk/openai-compatible",
      "options": { "baseURL": "http://127.0.0.1:1234/v1" },
      "models": { "my-model": { "name": "My Local Model" } }
    }
  }
}
```

- Model ids are `provider/model` (slash-separated), except AWS inference
  profiles where the `models` map **key is the display id and `id` is the ARN**.
- `blacklist` / `whitelist` take arrays of model ids **as shown in the `/models`
  picker**; whitelist narrows, blacklist removes, and they compose
  (whitelist first, then blacklist).
- Credentials live in `~/.local/share/opencode/auth.json` (written by
  `/connect`).
- **Model catalog comes from models.dev** — OpenCode uses the AI SDK and
  Models.dev for 75+ providers. npm package: `@opencode-ai/models`.
- `opencode models` CLI lists the catalog; `opencode auth list` shows auth.

### 5.5 Cline

- Repo: https://github.com/cline/cline
- Provider schema: `apps/cline-hub/src/webview/src/lib/provider-schema.ts`
- Model type: `apps/vscode/src/shared/api.ts`

**Provider settings file** (`~/.cline/settings/providers.json`-style; the repo
fixture `apps/cli/src/tests/configs/default/data/settings/providers.json`):

```json
{
  "version": 1,
  "lastUsedProvider": "cline",
  "providers": {
    "cline": {
      "settings": {
        "provider": "cline",
        "auth": { "accessToken": "…", "refreshToken": "…", "expiresAt": 1899578924000, "accountId": "…" },
        "model": "anthropic/claude-sonnet-4.6"
      },
      "updatedAt": "2026-01-01T00:00:00.000Z",
      "tokenSource": "oauth"
    }
  }
}
```

**Model list format** — `ProviderModel` (capability-typed, no pricing required):

```typescript
export interface ProviderModel {
  id: string;
  name: string;
  supportsAttachments?: boolean;
  supportsVision?: boolean;
  supportsReasoning?: boolean;
  operation?: ModelOperation;
  inputModalities?: ModelModality[];
  outputModalities?: ModelModality[];
}
```

**Cline's internal `ModelInfo`** (`apps/vscode/src/shared/api.ts`) is the
richer, OpenRouter-shaped one:

```typescript
export interface ModelInfo {
  name?: string
  maxTokens?: number
  contextWindow?: number
  maxInputTokens?: number
  supportsImages?: boolean
  supportsPromptCache: boolean
  supportsReasoning?: boolean
  inputPrice?: number
  outputPrice?: number
  thinkingConfig?: {
    maxBudget?: number
    outputPrice?: number
    outputPriceTiers?: PriceTier[]
    geminiThinkingLevel?: "low" | "high"
    supportsThinkingLevel?: boolean
  }
  // …
}
```

Cline's OpenRouter provider piggybacks on the shared OpenRouter catalog key
(`refreshOpenRouterModels.ts` → `resolveProviderModelsRecord(controller,
"openrouter")`). **Cline does not ship a static openrouter model JSON list** —
it fetches live. The Roo Code docs confirm the same: "Roo Code automatically
fetches all available models from OpenRouter's API (100+ models from various
providers)."
(https://docs.roocode.com/providers/openrouter)

### 5.6 Roo Code

- Docs: https://docs.roocode.com/providers/openrouter

Same as Cline in substance — provider + API key + a model dropdown; models are
fetched live from the provider's API. **No static model JSON.** Roo Code does
add a manual "Enable Prompt Caching" checkbox for Gemini via OpenRouter
because of response-delay issues with Google's caching through the aggregator.

### 5.7 Gemini CLI

- Docs: https://geminicli.com/docs/reference/configuration.md
- Schema: https://raw.githubusercontent.com/google-gemini/gemini-cli/main/schemas/settings.schema.json
- Model routing: https://geminicli.com/docs/cli/model-routing

**Important**: per the docs site banner, "Gemini CLI was replaced by Antigravity
CLI on June 18th, 2026" for unpaid-tier and Google One users, and "Gemini CLI
has not been optimized for Gemini 4 Argon."

**Settings**: JSON at `/etc/gemini-cli/system-defaults.json`,
`~/.gemini/settings.json`, `./.gemini/settings.json`, `/etc/gemini-cli/settings.json`.
Precedence: defaults < system-defaults < user < project < system < env vars <
CLI args.

**`model` object** (from `settings.schema.json`):
```json
{ "model": { "name": "gemini-3-pro-preview", "maxSessionTurns": -1,
             "summarizeToolOutput": {...}, "compressionThreshold": 0.5,
             "disableLoopDetection": false, "skipNextSpeakerCheck": false } }
```

**`modelConfigs`** — an alias system with `extends` inheritance:
```json
{ "modelConfigs": { "aliases": {
    "base":      { "modelConfig": { "generateContentConfig": { "temperature": 0, "topP": 1 } } },
    "chat-base": { "extends": "base", "modelConfig": { "generateContentConfig": { "thinkingConfig": { "includeThoughts": true }, "temperature": 1, "topP": 0.95, "topK": 64 } } },
    "gemini-3-pro-preview": { "extends": "chat-base-3", "modelConfig": { "model": "gemini-3-pro-preview" } }
  } } }
```

**Model selection precedence**: `--model` flag → `GEMINI_MODEL` env →
`model.name` in settings.json → local Gemma router (experimental) → default
(`auto`).

**Auto mode**: `Auto (Gemini 3)` = `gemini-3-pro-preview, gemini-3-flash-preview`;
`Auto (Gemini 2.5)` = `gemini-2.5-pro, gemini-2.5-flash`.

**Local Model Routing (Experimental)**: a locally-running **Gemma** model makes
the routing decisions instead of a hosted model — directly relevant to your
"free local model as the router itself" goal. Setup via the `gemini gemma`
command.

### 5.8 Summary matrix

| Tool | Config format | Model id style | Model list source | Aliases? | Fallback mechanism |
|---|---|---|---|---|---|
| **Hermes** | YAML (`~/.hermes/config.yaml`) | raw wire id | hardcoded `_PROVIDER_MODELS` + live `/v1/models` + models.dev | picker-only (`model_search.py`) | `fallback_providers:` ordered chain + typed `FailoverReason` |
| **Claude Code** | JSON (`~/.claude/settings.json`) | alias (`sonnet`/`opus`/`haiku`) or full id | built-in + `GET /v1/models` gateway discovery | **yes, first-class** | `fallbackModel` array (max 3, turn-scoped) |
| **Codex CLI** | TOML (`~/.codex/config.toml`) | slug + `model_provider` | `codex-rs/models-manager/models.json` (capability flags) + `model_catalog_url` | profiles | retry counts per provider; `model_provider` switch |
| **OpenCode** | JSON/JSONC (`opencode.json`) | `provider/model` | **models.dev** + provider `/models` | provider `whitelist`/`blacklist` | provider auth errors |
| **Cline** | JSON (`providers.json`) | raw id (often `provider/model`) | live provider API | provider-scoped `ProviderModel` list | provider-specific |
| **Roo Code** | VS Code settings UI + JSON | raw id | live provider API | none documented | provider-specific |
| **Gemini CLI** | JSON (`~/.gemini/settings.json`) | model name or `auto` | built-in + `modelConfigs` aliases | **yes** (`extends`) | `ModelAvailabilityService`, user-prompted; silent chain for internal calls |
| **LiteLLM** | YAML (`config.yaml`) | `model_name` alias + `litellm_params.model` | `model_list` + `model_info` overrides | **yes** (`model_name` groups) | `fallbacks:` map + cooldowns + health checks + Auto Router |
| **upb (yours)** | YAML (`~/.config/upb/routes.yaml` + `router/providers.yaml`) | `model_map` alias + `model_prefix` | declared + live `/v1/models` (`upb verify`) | **yes** (`model_map`) | provider cooldown + alternate-provider failover |

---

## 6. Decision framework for the router of routers

### 6.1 Layered design

```
┌──────────────────────────────────────────────────────────────┐
│ L4  Policy      capability classes, floors, budget,           │
│                 session pinning, allowed pools              │
├──────────────────────────────────────────────────────────────┤
│ L3  Selection   classifier → tier → cheapest passing model   │
│                 (heuristic | LLM | JEV | custom plugin)       │
├──────────────────────────────────────────────────────────────┤
│ L2  Registry    canonical model → per-provider wire IDs,     │
│                 capabilities, pricing, entitlement state     │
├──────────────────────────────────────────────────────────────┤
│ L1  Transport   provider adapters, protocol translation,      │
│                 credentials, quotas                          │
└──────────────────────────────────────────────────────────────┘
```

**Where `upb` sits today:** L1 + L2 (partial, ID-keyed) + a slice of L4
(priority, cooldown, pricing). **Missing:** a real L3 classifier and a
canonical L2 that is capability-addressed.

### 6.2 The canonical registry — concrete schema

**Do not reinvent models.dev.** Use it as the L2 base and add only what it
lacks (your provider pools, entitlements, subscription-vs-metered).

```yaml
# registry.yaml — the single source of truth
version: 1
meta:
  models_dev_url: https://models.dev/api.json
  models_dev_etag: "…"          # from ~/.hermes/models_dev_cache.json
  refreshed_at: "2026-10-23T…Z"

# ── Capability classes: stable names, not IDs ──────────────────
classes:
  coding.strong:
    requires: { tool_call: true, context_window: ">=200000" }
    preferred: { reasoning: true }
  coding.fast:
    requires: { tool_call: true, context_window: ">=32000" }
    max_cost_per_1m: { input: 1.0, output: 4.0 }
  coding.minimal:
    requires: { tool_call: true }
  reasoning.deep:
    requires: { reasoning: true }
  vision.any:
    requires: { attachment: true }
  local.free:
    requires: { open_weights: true }
    max_cost_per_1m: { input: 0, output: 0 }

# ── Provider pools: billing model matters ─────────────────────
pools:
  anthropic-subscription:
    billing_model: subscription
    providers: [anthropic]
  codex-subscription:
    billing_model: subscription
    providers: [openai-codex]
  gemini-subscription:
    billing_model: subscription
    providers: [gemini]
  local-lmstudio:
    billing_model: free
    providers: [lmstudio]
    base_url: http://127.0.0.1:1234/v1
    requires_api_key: true        # ← LM Studio returns invalid_api_key without it
  free-tier:
    billing_model: free
    providers: [opencode-zen]
  metered:
    billing_model: metered
    providers: [openrouter, litellm, zai, mistral, deepseek, alibaba]

# ── Model bindings: class → concrete provider+id, with fallbacks ─
bindings:
  - class: coding.strong
    candidates:
      - { pool: anthropic-subscription, provider: anthropic, model: claude-opus-5 }
      - { pool: codex-subscription,   provider: openai-codex, model: gpt-5.3-codex }
      - { pool: metered,              provider: openrouter,   model: anthropic/claude-sonnet-5.5 }
    fallback_class: coding.fast

  - class: coding.fast
    candidates:
      - { pool: local-lmstudio, provider: lmstudio, model: "qwen2.5-coder:32b" }
      - { pool: free-tier,     provider: opencode-zen, model: deepseek-v4-flash-free }
      - { pool: metered,       provider: openrouter,   model: "z-ai/glm-5.3-flash" }
    fallback_class: coding.minimal

  - class: coding.minimal
    candidates:
      - { pool: local-lmstudio, provider: lmstudio, model: "llama3.2:3b" }
```

**Resolution algorithm** (run per request or per session):

```
resolve(request, class):
  1. candidates = bindings[class].candidates
  2. filter by capability floors (from classes[class].requires)
  3. filter by health (cooldown registry) and entitlement (last known probe)
  4. if session_affinity and a pin exists for session_id:
       use pin if it still passes 2+3; else re-pin
  5. rank remaining by (billing preference, cost, latency, cached-ness)
  6. execute; on failure classify → apply action matrix → next candidate
```

### 6.3 Concrete build steps for `upb`

**Step 1 — canonical registry file + generator.**
Add `registry.yaml` (schema above). Write `upb registry sync` that:
- fetches `https://models.dev/api.json` (cache + ETag, like Hermes does);
- joins each provider-scoped model to its `canonical_model_id`;
- resolves each `class` to concrete `(provider, model)` candidates;
- writes a merged `router/providers.yaml` (or a new `router/registry.yaml`).

**Step 2 — make `/v1/models` Claude-Code-compatible.**
Return `{"data":[{"id","display_name","description"}]}` and keep the
`claude`/`anthropic` substring filter in mind (your gateway serves non-Claude
models too, so you may want a different filter — but if you want Claude Code's
gateway discovery to work out of the box, emit `claude-*` aliases for your
model_map entries, which `router/providers.yaml.example` already does:
`claude-opus-4-6 → litellm/qwopus3.5-9b-coder`, etc.).

**Step 3 — extend `upb verify` into a standing health job.**
`upb verify` already does catalog-diff (`missing_upstream` / `new_upstream`)
and a billable 1-token probe. Add:
- `--background` mode on a timer (LiteLLM's `background_health_checks` +
  `health_check_interval` + `enable_health_check_routing`);
- `ignore_transient_errors` (don't cooldown on 429/408);
- persist per-(provider,model) entitlement state so the router can skip
  unentitled models *before* calling;
- probe via the cheapest endpoint first (embed/tokenize), escalating to the
  1-token chat probe only when needed.

**Step 4 — adopt a typed failure taxonomy.**
Port Hermes' `FailoverReason` enum + recovery-hint bundles into `upb`'s
`router/src/utils/errors.ts` (which today has only a 3-value
`ErrorCategory`: RETRYABLE / NON_RETRYABLE / PROVIDER_ERROR). Replace with a
`FailureClass` enum and an action matrix.

**Step 5 — add the L3 classifier.**
Start with the LiteLLM heuristic (7 dimensions, ~40 lines — the
`Not-Diamond/SimpleClawRouter` 14-dimension variant is a good second
reference), then optionally escalate to an LLM classifier or a local Gemma
classifier for the routing decision itself (Gemini CLI's Local Model Routing
proves this pattern works).

**Step 6 — session pinning.**
Add `session_affinity` keyed by session id with a TTL, so an agentic loop
stays on one model and keeps its prompt cache.

### 6.4 What to copy from whom

| Concern | Copy from | Why |
|---|---|---|
| Canonical model registry | **models.dev** (`catalog.json`) | 610 canonical models + 85% coverage; already consumed by Hermes & OpenCode; don't rebuild. |
| Tier/classification model | **LiteLLM Auto Router** (`complexity_router_config`) | Closest thing to the target; battle-tested knobs; sub-ms heuristic. |
| Failure taxonomy | **Hermes `error_classifier.py`** | 30+ typed reasons with recovery hints; the `should_fallback`/`should_compress`/`should_rotate_credential` triple is exactly right. |
| Capability-typed model schema | **Codex `models.json`** | `slug` + capability booleans + `context_window`/`max_context_window`; cleanest separation of capability from provider. |
| Gateway model-discovery contract | **Claude Code LLM gateway protocol** | `GET /v1/models?limit=1000` + `{"data":[{id,display_name,description}]}`; de-facto standard. |
| Alias/fallback UX | **Claude Code** (`fallbackModel`, max 3, context-window floor) | Well-specified semantics; the context-window floor rule is easy to get wrong. |
| Local-model-as-router | **Gemini CLI** (`gemini gemma` Local Model Routing) | Proves a local Gemma can make routing decisions. |
| Cost-aware pair routing | **RouteLLM** (`mf` router + threshold calibration) | If you want learned routing rather than heuristics; read `calibrate_threshold.py` before trusting any threshold. |
| Provider failover mechanics | **LiteLLM** (`fallbacks`, `allowed_fails_policy`, `cooldown_time`, health-check routing) | Complete, documented, production-proven. |

---

## 7. Unverified / flagged

| Claim | Status |
|---|---|
| Not Diamond pricing `$0.05/1M tokens routed`, 100–150 ms latency | **UNVERIFIED** — docs paths returned "Page Not Found"; from secondary comparison pages only. |
| Martian pricing `$20/5,000 requests`, "20–97% savings" | **UNVERIFIED** — docs.martian.ai returned an empty body; from secondary sources. |
| Not Diamond ranks 12th/12 on RouterArena | **UNVERIFIED** — from a competitor's blog (orcarouter.ai). |
| Martian pivoted to ARES/K-Steering | **UNVERIFIED** — from a competitor's blog. |
| RouterArena leaderboard values | Not scrapeable (JS SPA); only LiteLLM's published RouterArena numbers (74.5% cheaper @ 87.3% quality, 8,399 queries) were seen, and those are vendor-reported. |
| All LiteLLM Auto Router savings figures | Vendor-reported, not independently verified. |
| RouteLLM "3.66× cost saving at 95% GPT-4 quality" | From the ICLR paper / project README — peer-reviewed, but measured on GPT-4/Mixtral-8x7B, not modern models. |
| `docs.cline.bot/providers/openrouter` | **UNVERIFIED** — the page returned an empty body on every fetch attempt. Cline's formats above are from its **source code** on GitHub, which is stronger evidence. |
| Gemini CLI → Antigravity CLI replacement (2026-06-18) | Stated in a site-wide banner on geminicli.com; the Gemini CLI docs are frozen (last updated Mar/Apr 2026). |
| `upb verify` runtime behavior | **NOT EXECUTED** — `python3-yaml` is missing on this machine and the invocation with the Hermes venv was declined. The code path was *read* (`cli/upb` lines 828–953) but not run. |
| The user's LM Studio at `127.0.0.1:1234` | **VERIFIED reachable** — returned HTTP 200 with `invalid_api_key` (bearer token required). Model list not retrieved. |

---

## 8. Source URLs (all fetched during this research)

**Routing / state of the art**
- https://arxiv.org/abs/2406.18665 · https://arxiv.org/html/2406.18665v4
- https://proceedings.iclr.cc/paper_files/paper/2025/file/5503a7c69d48a2f86fc00b3dc09de686-Paper-Conference.pdf
- https://github.com/lm-sys/RouteLLM
- https://www.lmsys.org/blog/2024-07-01-routellm/
- https://github.com/lm-sys/RouteLLM/blob/main/examples/routing_to_local_models.md
- https://docs.notdiamond.ai/llms.txt · https://docs.notdiamond.ai/docs/quickstart-routing.md
- https://docs.notdiamond.ai/docs/pre-trained-router-code.md
- https://notdiamond.ai/blog/interactive-benchmarks-a-new-methodology-for-evaluating-model-routing
- https://martian.ai/ · https://docs.martian.ai/ *(empty)*
- https://routerarena.ai/ *(JS SPA)*

**LiteLLM (the current state of the art)**
- https://docs.litellm.ai/llms.txt
- https://docs.litellm.ai/docs/auto_router/index.md
- https://docs.litellm.ai/docs/proxy/auto_routing.md
- https://docs.litellm.ai/docs/proxy/health_check_routing.md
- https://docs.litellm.ai/docs/proxy/reliability.md
- https://docs.litellm.ai/docs/routing.md
- https://docs.litellm.ai/docs/auto_router/decision_classifiers.md
- https://docs.litellm.ai/docs/auto_router/prompt_caching.md

**Model catalogs**
- https://models.dev/api.json (230 providers, 8,449 models)
- https://models.dev/catalog.json?type=all (canonical `models` layer: 610 entries)
- https://models.dev/ · https://github.com/anomalyco/models.dev
- https://openrouter.ai/api/v1/models (468 models)
- npm `@opencode-ai/models`

**Claude Code**
- https://docs.claude.com/en/docs/claude-code/model-config.md
- https://docs.claude.com/en/docs/claude-code/llm-gateway-protocol.md
- https://docs.claude.com/en/docs/claude-code/settings-reference.md
- https://docs.claude.com/en/docs/claude-code/settings.md

**Codex CLI**
- https://developers.openai.com/codex/config-reference.md
- https://developers.openai.com/codex/config-basic.md
- https://raw.githubusercontent.com/openai/codex/main/codex-rs/models-manager/models.json

**OpenCode**
- https://opencode.ai/docs/config/ · https://opencode.ai/docs/providers/

**Cline / Roo Code**
- https://github.com/cline/cline
- `apps/cline-hub/src/webview/src/lib/provider-schema.ts`
- `apps/vscode/src/shared/api.ts`
- `apps/cli/src/tests/configs/default/data/settings/providers.json`
- https://docs.roocode.com/providers/openrouter

**Gemini CLI**
- https://geminicli.com/docs/reference/configuration.md
- https://geminicli.com/docs/cli/model-routing
- https://raw.githubusercontent.com/google-gemini/gemini-cli/main/schemas/settings.schema.json

**Local source read (not fetched over the network)**
- `/Users/fabiofalopes/.hermes/hermes-agent` @ `be7f7b1af9` —
  `hermes_cli/models_catalog_static.py`, `hermes_cli/model_search.py`,
  `hermes_cli/provider_catalog.py`, `hermes_cli/fallback_config.py`,
  `hermes_cli/fallback_cmd.py`, `hermes_cli/models_local.py`,
  `hermes_cli/models_pricing.py`, `agent/models_dev.py`,
  `agent/error_classifier.py`, `cli-config.yaml.example`
- `/Users/fabiofalopes/projetos/hub/upb` @ `e75c77f` —
  `router/src/index.ts`, `router/src/utils/cooldown.ts`,
  `router/src/utils/errors.ts`, `router/src/middleware/router-config.ts`,
  `router/src/adapters/registry.ts`, `router/providers.yaml.example`,
  `config/routes.yaml.example`, `cli/upb`
