# The model list you can trust

> A picker that shows only what works, greys out what your plan refuses, and
> hides what is gone. Plus the roadmap for keeping it fresh without thinking
> about it.

**Status 2026-10-23.** The health gate is built and working
(`tools/health_gate.py`). The doc-fetcher and metrics layer are designed here
but not yet built. Read the *built* sections as done and the rest as the plan.

---

## Part 1 — The picker (built)

### What is broken today

`/model` shows every model a provider **lists**. It does not know whether your
plan can **call** it. So:

- you pick `deepseek-v4-pro` → 402 "not included in your free usage"
- you pick `qwen3-coder-next` → "was retired on July 15, 2026"
- you pick `mistral-large-latest` → 401, because the key is `'your-key-here'`

None of that is visible at selection time.

### What Hermes already gives us

Two mechanisms, both built, both unused for this:

**1. `custom_providers[].models:` + `discover_models: false`**
(`hermes_cli/model_switch_providers.py:573`) — the picker shows *exactly* that
list and stops probing. A dead model is simply not in the list. This is the
"don't offer what you can't have" lever.

**2. `model_catalog.excluded_providers`**
(`hermes_cli/inventory.py:54`) — a provider slug or alias is hidden from the
picker entirely.

And the **grey-out rendering already exists**:
`hermes_cli/auth_model_picker.py:163` documents that models in
`unavailable_models` "render grayed out and unselectable with an upgrade link
to `portal_url`". The Nous free-tier path uses it — `partition_nous_models_by_tier`
(`hermes_cli/models.py:225`) splits a catalogue into `(selectable, unavailable)`
and the unavailable half renders dimmed.

**So the rendering is there. The partition is there for one provider. What is
missing is the general case.**

### The design

A **health gate**: probe every (provider, model) pair, sort into buckets, and
write the result back into the Hermes config using the two mechanisms above.

```
  probe (1-token call, real)
        │
        ▼
  ┌─────────────────────────────────────────┐
  │  bucket per (provider, model)            │
  ├─────────────────────────────────────────┤
  │  selectable    200                        │
  │  greyed        402 / 403   plan refuses   │
  │  retired       "was retired on <date>"    │
  │  busy          429         transient      │
  │  removed       404         gone           │
  │  provider-dead 401         key dead       │
  └─────────────────────────────────────────┘
        │
        ▼
  write back:
    custom_providers[].models = selectable only
    custom_providers[].discover_models = false
    model_catalog.excluded_providers += providers with nothing selectable
```

**Buckets are not permanent.** Re-run the scan and a model that starts working
— because you resubscribed, a trial ended, a plan upgraded — moves back to
`selectable` automatically. **That is the toggle-back-on mechanism: no manual
editing, no second config to keep in sync.** You resubscribe, the next scan
puts it back in the picker.

**`busy` (429) is deliberately kept separate** from `greyed`. A rate-limited
model is usually fine; excluding it because the provider was briefly busy
would be wrong. `busy` keeps the model selectable and just notes it.

**`retired` is its own bucket** because ollama names the date and the
replacement in the error body:

> `deepseek-v4-flash was retired on September 25, 2026. Try gemma4:31b-cloud`

That is the clearest churn signal available and it is currently thrown away.

### The tool

```console
$ python3 tools/health_gate.py --scan
scanned 70 provider/model pairs → ~/.hermes/cache/model_health_gate.json

  commandcode
    selectable (6): deepseek/deepseek-v4-pro, google/gemini-3.8-flash,
                    minimax/minimax-m3.1-flash, moonshotai/Kimi-K2.7-Code,
                    xai/grok-4.7, zai-org/GLM-5.3
    greyed     (1): gpt-5.4
    error      claude-sonnet-5-5: rejected — often a wrong dialect

  upb:ollama-cloud
    selectable (3): gemma4:31b, gpt-oss:120b, nemotron-3-ultra
    greyed     (7): deepseek-v4-pro, glm-5.2, kimi-k2.6, kimi-k2.7-code,
                    minimax-m2.7, minimax-m3, mistral-large-3:675b
    busy       (3): devstral-2:123b, nemotron-3-super, qwen3-coder-next
    RETIRED    (7): deepseek-v3.2, deepseek-v4-flash, gemini-3-flash-preview,
                    glm-5, glm-5.1, qwen3-coder:480b, qwen3.5:397b

$ python3 tools/health_gate.py --apply    # write it into ~/.hermes/config.yaml
$ python3 tools/health_gate.py --show     # what the gate currently says
```

**What the first scan found, immediately:**

| Finding | Count | Meaning |
|---|---|---|
| retired models on ollama-cloud | 7 | ids that will never work again |
| dead mistral models | 9 | the key is `'your-key-here'` |
| plan-gated alibaba models | 6 | valid token, every model 403 |
| plan-gated ollama models | 7 | valid token, outside your free plan |
| dead alibaba-coding-plan token | 4 providers | one expired key, four provider ids |

### Cost and safety

The probe is `max_tokens: 1`. It is **billable on metered models** — but a
model that is plan-locked returns 402 *without* being charged, so the probe
mostly costs nothing. On a 1-token call against a metered model the cost is
fractions of a cent.

Two safeguards worth having:

- **Never probe more often than the plan changes.** The scan is not a hot
  loop; it is a cron job (below).
- **`upb registry` is the companion.** The registry knows *which* models
  exist and their canonical identity; the gate knows *which you can use*.
  Together they answer "what should I be running" without a manual list.

### The cron job

```yaml
# hermes cron create — weekly, off the hours you are awake
name: model-health-scan
schedule: "17 4 * * 1"     # Mondays 04:17
```

The scan writes the gate and, on a `--apply` flag, the config. A summary of
what changed goes to a channel you read. **The signal you want is "model X
retired" or "provider Y is back"** — not a weekly dump.

---

## Part 2 — Keeping the information ready (designed)

Your point: automate the doc fetches, always official docs, so everything
downstream is stable and usable.

### The problem with fetching docs

Fetching provider docs is deceptively hard:

- **docs move.** A URL that worked last quarter 404s now.
- **the same fact lives in three places** — a pricing page, a models API, and
  a changelog post — and they disagree.
- **HTML is not data.** A pricing table is a page. Scraping it means
  maintaining a scraper.
- **the API is the data.** Most providers expose a machine-readable catalog
  that is *more* authoritative than their docs: models.dev, OpenRouter's
  `/api/v1/models`, Anthropic's `/v1/models`, Ollama's `/v1/models`.

### The design: docs as a *cache*, facts as *authoritative*

```
  ┌── official sources ────────────────────────────────┐
  │                                                    │
  │  machine-readable  →  authoritative facts          │
  │    models.dev/api.json        (canonical identity) │
  │    {provider}/v1/models        (what's served)     │
  │    provider /v1/models        (what YOU can call) │
  │                                                    │
  │  human-readable    →  context, caveats, changelog │
  │    docs pages                 (fallback + prose)  │
  │    changelog feeds            (what changed)      │
  └───────────────────────┬────────────────────────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  the registry    │
                 │  (upb registry)  │
                 │  models{}        │
                 │  bindings{}      │
                 │  slots{}         │
                 └────────┬─────────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
          the picker   the gate    routing
```

**Rules:**

1. **A machine-readable API always beats a scraped page.** The docs are for
   the *why* (a plan's terms, a deprecation policy); the API is for the
   *what*.
2. **Every fact carries a source and a timestamp.** A price without a source
   is a guess.
3. **Docs are fetched on a schedule, not on demand.** A slow provider must
   never block a picker open. This is the same discipline Hermes already
   applies to the model catalog (`model_catalog.ttl_minutes: 20`).
4. **Never fetch during a turn.** The health gate probes the *providers*,
   which is fast. Doc fetching is a background job.

### What to fetch, and from where

| Source | URL | Gives | Cadence |
|---|---|---|---|
| models.dev | `models.dev/api.json` | canonical ids, pricing, capabilities | 4h (already cached by Hermes) |
| provider catalogs | `{base}/models` | what each provider serves now | hourly |
| OpenRouter | `/api/v1/models` | cross-provider aliasing + expiry | 6h |
| LiteLLM prices | `model_prices_and_context_window.json` | deprecation dates with sources | 24h |
| provider docs | per-provider | plan terms, changelog, deprecation policy | weekly + on change |
| changelog feeds | RSS/Atom where they exist | "model X retired on <date>" | daily |

**The changelog feeds are the highest-value, lowest-effort source.** A
provider announcing a model retirement is a machine-readable fact if you
subscribe to their feed. The ollama error message
(`"was retired on September 25, 2026"`) shows the providers *do* publish
this — they just do not publish it in a place you can query.

### Where it lands

All of it lands in **one place**: the upb registry. The registry already has
the schema for `models{}` (canonical identity, capabilities, context window),
`bindings{}` (provider + id + status + price + source), and `slots{}`
(intent). What is missing is the *fetcher* that populates it from all of the
above, and the *snapshot* that records what the registry said on a given day.

That is `docs/REGISTRY.md` and `docs/research/MODEL-REGISTRY-RESEARCH.md`.
The research doc already names the sources and their provenance rules; the
fetcher is unbuilt.

---

## Part 3 — Metrics and monitoring (designed)

### The question metrics should answer

Not "how many tokens" — you know that. The questions that actually change
decisions:

1. **Which provider+key+model am I actually spending on?** (LiteLLM does this
   for API keys; you need it for the subscription side too.)
2. **How much of my Claude Max / Codex allowance is burned?** (Nobody can
   answer this from API payloads — it lives in the provider's rate-limit
   state. `gpt-load` parses it; `ClaudeBar`/`CodexBar` poll it.)
3. **Which provider do I *route* through most, and what does that cost?**
   (the upb router's `/usage` endpoint already answers this — it was
   verified live during the integration test.)
4. **Is the health gate telling the truth?** (i.e. did a "selectable" model
   fail in the wild?)

### The stack

```
  ┌─ local models ────────────────┐
  │  LM Studio :1234               │
  │  lms log stream --stats        │  ← per-model tok/s, TTFT
  └───────────────────────────────┘
  ┌─ cloud API + rotated keys ────┐
  │  LiteLLM proxy                 │  ← per-key spend, virtual-key budgets
  │  (already in your stack)       │
  └───────────────────────────────┘
  ┌─ subscription agents ──────────┐
  │  Claude Code / Codex JSONL     │  ← ccusage: what you burned
  │  provider quota APIs           │  ← ClaudeBar/CodexBar: what is LEFT
  └───────────────────────────────┘
  ┌─ routing layer ────────────────┐
  │  upb router /usage             │  ← by_provider, by_model, cost_usd
  └───────────────────────────────┘
```

**The honest split:** API spend and subscription quota are different questions
with different sources. No single tool answers both. See
`docs/diagrams/observability-split.png`.

**What is genuinely missing for you:** the upb router is not running, so its
`/usage` — the one source that would tie routing decisions to cost — is
dark. That is a deployment blocker, not a design problem.

### What to measure, minimally

| Metric | Source | Why |
|---|---|---|
| requests + tokens by provider+model | upb `/usage` | routing decisions |
| cost by key | LiteLLM `/key/info` | which key to rotate |
| plan burn (5h/weekly) | ClaudeBar / CodexBar | when to switch to local |
| tok/s + TTFT by model | `lms log stream --stats` | local model choice |
| **gate accuracy** | compare gate vs reality | is the picker lying? |
| **model churn rate** | registry snapshots over time | how fast does this rot? |

That last one is the interesting metric. Once the registry snapshots daily,
"how many models were retired or renamed this month" becomes a number — and
that number tells you how often to run the scan.

### Alerting

Two signals worth waking you for:

- **A model you actively use was retired.** The scan found 7 on ollama-cloud
  and your config referenced 10 that were not served. That should be a
  notification, not a discovery.
- **Your working set changed.** A provider went from 6 models to 0 (your
  alibaba token expired and you did not notice). That is a subscription event
  masquerading as a config problem.

---

## Part 4 — Sign-in, OIDC, and the rest (noted, not designed)

You mentioned signup and OIDC. Worth saying plainly where that fits:

- **Hermes has OAuth for several providers already** — OpenAI Codex (device
  code), Qwen, MiniMax, xAI, Nous Portal. `hermes auth add <provider>`.
- **The credential pool already handles rotation** — 18 credentials across 15
  providers, with `fill_first` strategy and per-credential cooldowns.
- **Your openai-codex token is expired** (`stale-credential`), which is the
  exact failure OIDC refresh exists to prevent. `hermes auth refresh` exists.
- **A generic OIDC provider** (any endpoint that speaks OIDC for a coding
  plan) would be new Hermes work, not upb work. The upb router already
  accepts a bearer token from anywhere, so an OIDC provider just needs to
  present a token.

---

## Sequencing

| # | What | State | Effort |
|---|---|---|---|
| 1 | health gate | **built** | done |
| 2 | wire the gate into the picker | **built** (`--apply`) | done |
| 3 | cron the scan + notify on churn | to do | small |
| 4 | registry fetcher (models.dev + catalogs + changelogs) | to do | medium |
| 5 | deploy the upb router → `/usage` becomes live | to do | blocked on converter + launchd |
| 6 | LiteLLM per-key spend for the rotated keys | to do | small |
| 7 | ccusage + ClaudeBar for subscription burn | to do | small |
| 8 | registry snapshots → churn-rate metric | to do | medium |
| 9 | generic OIDC provider | not designed | large |

**The next three are the ones that matter.** Steps 1–2 are done and already
found 7 retired models and 12 broken provider/model pairs you were unaware of.
Step 3 makes that automatic. Step 5 turns on the one metric source you own.
