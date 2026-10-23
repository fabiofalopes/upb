# Model Registry Research — sources, config snapshots, and a churn-resistant schema

**Scope:** authoritative open-source model metadata for a personal multi-provider AI
setup (LM Studio + LiteLLM + rotating cloud keys + Claude Code/Codex subscriptions),
plus the config-snapshot/secrets problem and the "providers keep changing model ids"
pain point.

**Status:** research findings. Every number below was measured against live APIs on
2026-10-23 unless noted. No schema changes have been applied to upb yet.

---

## Executive summary

1. **models.dev (`anomalyco/models.dev`, MIT, ★7.3k) is the best primary source.** It is
   the only catalog that exposes *provider-scoped* lifecycle status (`status = deprecated`)
   plus a `canonical_model_id` that survives provider-specific naming. 230 providers,
   8,849 model bindings, 619 canonical models. It is a git repo with machine-readable TOML
   per model, so **its git history is a free "what was the catalog at time T" oracle**.
2. **LiteLLM's `model_prices_and_context_window.json` is the best *date-carrying*
   source.** 866 models carry `deprecation_date`; 731 of them also carry a `source` URL
   pointing at the upstream announcement. It is a 3 MB single-file snapshot — trivial to
   snapshot daily.
3. **Deprecation is a property of the (provider, model) pair, not of the model.** 315
   model ids have different status at different providers in models.dev. A registry keyed
   on model id alone is *wrong*.
4. **Only OpenRouter exposes both aliasing and expiry.** 19 `~provider/model-latest`
   aliases and 12 `expiration_date` values. The `-latest` alias family is the single most
   valuable churn-absorbing mechanism found anywhere.
5. **AWS Bedrock's `ListFoundationModels` is the only provider-native lifecycle API**
   (`modelLifecycle`: `startOfLifeTime` / `legacyTime` / `endOfLifeTime` / `status`). It
   is the reference implementation a registry should mirror.
6. **upb already has the scaffolding.** `upb verify` (cli/upb:885) audits declared models
   against live `/models` catalogs, and `routes.yaml` already carries `key:` slots,
   `trust_zone:`, `priority:`, and `enabled:`. What is missing is a *registry file* and
   a *deprecation detector* — both fit the existing shape.

---

## Part A — Model catalog / metadata sources

### A.1 Comparison matrix

| Source | License | Endpoint | Model id | Provider | Context | Max out | In/Out price | Release date | Deprecation | Capabilities | Still served? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **models.dev** | MIT | `GET https://models.dev/api.json` | ✅ `id` | ✅ per-provider | ✅ `limit.context` | ✅ `limit.output` | ✅ `cost.input/output/cache_read` | ✅ `release_date` | ✅ `status: deprecated\|beta\|alpha` (no date) | ✅ reasoning/tool_call/structured_output/attachment/`modalities` | ✅ by absence from catalog |
| **LiteLLM prices JSON** | MIT | `raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` | ✅ | ✅ `litellm_provider` | ✅ `max_input_tokens` | ✅ `max_output_tokens` | ✅ per-token | ➖ via `source` URL only | ✅ **`deprecation_date` (ISO date)** + `source` | ✅ 20+ `supports_*` flags | ➖ only by absence |
| **OpenRouter models API** | public API | `GET https://openrouter.ai/api/v1/models` | ✅ `id` | ➖ (see `/endpoints`) | ✅ `context_length` | ✅ `top_provider.max_completion_tokens` | ✅ `pricing.prompt/completion` | ✅ `created` (epoch) | ✅ **`expiration_date`** | ✅ `supported_parameters`, `architecture`, `reasoning` | ✅ by presence |
| **OpenRouter endpoints API** | public API | `GET /api/v1/models/{slug}/endpoints` | ✅ `model_id` | ✅ `provider_name` | ✅ | ✅ | ✅ incl. tiered `overrides` | ➖ | ➖ | ✅ `supported_parameters`, `supports_tool_choice` | ✅ `status: 0` |
| **TrueFoundry models** | MIT | git `truefoundry/models` | ✅ | ✅ per-dir | ✅ `limits` | ✅ | ✅ | ➖ | ✅ **`isDeprecated: true`** | ✅ `features[]`, `modalities` | ➖ |
| **OpenModels** | ➖ | git `openmodelsrun/openmodels` | ✅ canonical | ✅ separate `providers/` | ✅ | ✅ | ✅ `input_per_million` | ✅ `created_at` | ➖ | ✅ `capabilities[]` enum | ➖ |
| **HuggingFace Hub** | public API | `GET https://huggingface.co/api/models?full=true` | ✅ | ➖ `author` | ➖ | ➖ | ➖ | ✅ `createdAt` | ➖ | ⚠️ `tags[]` (free-form) | ➖ |
| **AWS Bedrock** | proprietary API | `ListFoundationModels` | ✅ | ✅ | ➖ | ➖ | ➖ | ➖ | ✅ **`modelLifecycle`** (start/legacy/end) | ➖ | ✅ `status` |

**Verdict per use case:**

- **Deprecation detection:** models.dev (`status`) + LiteLLM (`deprecation_date`) + AWS
  Bedrock (`modelLifecycle`) + TrueFoundry (`isDeprecated`). OpenRouter's `expiration_date`
  is about *its own catalog entry expiring*, which correlates but is not the same thing.
- **Detecting that a provider's model id changed:** OpenRouter (`canonical_slug` ≠ `id`,
  plus `alias_target`) and models.dev (`canonical_model_id` vs per-provider `id`) are the
  only two that model the rename explicitly. LiteLLM does not — it silently keeps the old
  key with a `deprecation_date`.
- **Still served:** all of them, but only via *absence* from the catalog. None exposes a
  positive `served: true`. models.dev is the only one where a provider can drop a model
  while the canonical model survives elsewhere.

### A.2 models.dev — the primary source

Repo: `anomalyco/models.dev` — MIT, ★7,353, default branch `dev`, last push 2026-10-23.
It is the source of truth behind `opencode`'s own model picker, so it is both
community-maintained *and* commercially exercised.

**API shape** (`https://models.dev/api.json`):

```
{
  "<provider_id>": {
    "id", "name", "env": [...], "npm", "api", "doc",
    "models": {
      "<model_id>": {
        "id", "name", "description", "family",
        "attachment": bool, "reasoning": bool, "reasoning_options": [...],
        "tool_call": bool, "structured_output": bool, "temperature": bool,
        "interleaved", "knowledge", "release_date", "last_updated",
        "modalities": {"input": [...], "output": [...]},
        "open_weights": bool,
        "limit": {"context": int, "output": int},
        "cost": {"input", "output", "cache_read"},
        "status": "deprecated" | "beta" | "alpha",   // ← absent = active
        "canonical_model_id": "<org>/<model>",       // ← churn-absorbing
        "provider": {...}, "type": "...", "experimental": bool
      }
    }
  }
}
```

Measured on the live API (230 providers, 8,849 bindings; `?type=all` → 8,911):

- `status` present on 966 entries: **893 `deprecated`**, 72 `beta`, 1 `alpha`.
- `canonical_model_id` present on 7,548 entries → **619 distinct canonical models,
  6,590 provider bindings (avg 10.6 providers per canonical model)**. `zhipuai/glm-5.3`
  is served by 89 providers.
- `release_date` + `last_updated` on every entry.

**The `canonical_model_id` + per-provider `status` combination is the core of the whole
problem.** The same canonical model can be `active` at one provider and `deprecated` at
another. Measured: **315 model ids have differing status across providers.** Example:

```
deepseek-v4-pro:
  alibaba-token-plan → active
  ollama-cloud       → active
  neuralwatt         → deprecated
```

A registry that stores `glm-5.2: deprecated` is wrong for `zai` and `alibaba-token-plan`.
**Status must be stored per (provider, model_id).**

**On-disk format (schema v2 TOML)** — this is what makes git-based snapshots viable:

```toml
# models/anthropic/claude-haiku-4-5.toml
schema = 2
name = "Claude Haiku 4.5 (latest)"
description = "Fast Claude lane for lightweight agents, office tasks, and responsive chat"
family = "claude-haiku"
open_weights = false
knowledge = "2025-02-28"
release_date = "2025-10-15"

[modalities]
input = ["text", "image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"]
output = ["text"]

[capabilities]
tools = { supported = true }
reasoning = { supported = true }
temperature = true
top_p = true
top_k = true

[limit]
context = 200_000
output = 64_000

[[benchmarks]]
name = "SWE-Bench Pro"
score = 39.45
```

Per-provider overrides live at `providers/<provider>/models/<model>.toml` and carry
provider-specific `status` plus free-text comments citing the upstream announcement:

```toml
# providers/minimax-coding-plan/models/MiniMax-M2.7.toml
# Plan requests for M2.5/M2.7 are routed to MiniMax-M3.1-Flash from 2026-10-19
#   (https://platform.minimax.io/docs/faq/models, ...)
schema = 2
name = "MiniMax-M2.7"
release_date = "2026-03-18"
status = "deprecated"
[limit]
context = 204_800
output = 131_072
```

**Git as a time machine.** The repo has continuous `chore(sync): update <Provider> model
catalog` commits (12+ on 2026-10-23 alone), on branch `dev`. So:

```bash
# what did models.dev think about glm-5.2 on 2026-06-01?
git -C models.dev rev-list -1 --before=2026-06-01 dev
git -C models.dev show <sha>:providers/zai/models/glm-5.2.toml
```

That is "what was I running at time T", solved — for the *catalog* half.

**Caching headers:** `ETag: "78864e10fd029a01dbb163e2ff4e18d6"`,
`Cache-Control: public, max-age=0, must-revalidate`. Use conditional GET
(`If-None-Match`) — Hermes already does this (`~/.hermes/models_dev_cache.etag`).

**Provider-id namespace:** models.dev uses gateway-agnostic ids (`zai`, `ollama-cloud`,
`alibaba-token-plan`, `opencode-go`) that mostly match a personal setup, but **not**
LiteLLM's (`zai` exists in LiteLLM, but `ollama-cloud` does not; LiteLLM uses
`fireworks_ai`, `bedrock`, `vercel_ai_gateway`, …). A registry needs its own provider
namespace with an explicit mapping table to each source's namespace. This namespace
mismatch is measured, not theoretical: LiteLLM matched only **15 of 38** of upb's
declared model ids under naive provider-prefixed lookup.

### A.3 LiteLLM `model_prices_and_context_window.json`

- 4,245 entries, ~3 MB, MIT, single file, updated in the same PR as code.
- **866 real `deprecation_date` values** (271 in the past, 595 upcoming), ISO `YYYY-MM-DD`.
- **731 of those 866 also carry `source`** — a URL to the upstream deprecation notice
  (e.g. `https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-ai21-labs-jamba-1-5-large.md`).
  This is the best *provenance* of any source: it lets a registry cite why a model is dead.
- 395 distinct `source` URLs across the file; 249 entries derive from the Azure Retail
  Prices API, 133 from OpenAI's pricing docs, 123 from Google Cloud, 117 from AWS
  Bedrock pricing.
- Richest capability flags: `supports_function_calling`, `supports_tool_choice`,
  `supports_vision`, `supports_reasoning`, `supports_response_schema`,
  `supports_prompt_caching`, `supports_web_search`, `supports_computer_use`,
  `supports_native_structured_output`, `supports_audio_input`, `supports_pdf_input`,
  `supports_video_input`, `supported_modalities`, `supported_output_modalities`, plus
  tiered pricing (`input_cost_per_token_above_272k_tokens`, `..._batches`,
  `..._priority`, `..._flex`), `rpm`, `tpm`, `supported_regions`.

**Data-quality caveat (important):** the deprecation dates are not uniformly meaningful.

- 49 entries are dated exactly `2026-10-23` (today) — a bulk "mark as retired" sweep, not
  real sunset dates.
- 81 entries are dated `2027-03-30`, and **all 81 are AWS Bedrock** (51 `bedrock`,
  26 `bedrock_converse`, 4 `bedrock_mantle`) — a provider-wide batch date, not
  per-model sunsets.
- Only 6 future-dated entries have a `-latest` id, so the "latest" pointers are
  correctly *not* marked deprecated.

**Conclusion:** treat LiteLLM's `deprecation_date` as a *hint* that needs corroboration,
never as ground truth on its own. A registry should store it with its `source` URL so
the claim is auditable.

### A.4 OpenRouter models + endpoints API

`GET https://openrouter.ai/api/v1/models` → 468 models, 790 KB, no auth.

**Unique fields nothing else has:**

- `canonical_slug` — the dated/pinned form of the id. **325 of 468 models have
  `id != canonical_slug`**:
  ```
  id:       deepseek/deepseek-v4.1-flash-1017
  canonical: deepseek/deepseek-v4.1-flash-20261017
  ```
- `alias_target` — 19 entries, the `-latest` family:
  ```
  ~openai/gpt-luna-latest        → openai/gpt-6-luna
  ~anthropic/claude-sonnet-latest → anthropic/claude-sonnet-5.5
  ~deepseek/deepseek-pro-latest   → deepseek/deepseek-v4-pro-0813
  ~z-ai/glm-latest                → z-ai/glm-5.3
  ~moonshotai/kimi-latest         → moonshotai/kimi-k3
  ```
  **This is the cleanest churn-absorbing primitive in the entire survey.** A config that
  says `~anthropic/claude-sonnet-latest` keeps working when the underlying model changes.
- `expiration_date` — only 12 models carry one (e.g. `poolside/laguna-s-2.1` →
  `2026-10-31`, `bytedance-seed/seed-2.0-code` → `2026-11-11`).
- `created` (epoch) — catalog turnover is real: **52 of 468 models were created in the
  last 30 days, 124 in 90 days** (range 2023-05-28 → 2026-10-21).
- `architecture.input_modalities/output_modalities`, `knowledge_cutoff`,
  `supported_parameters`, `reasoning.mandatory`, `benchmarks` (303 models have arena
  Elo data).

`GET https://openrouter.ai/api/v1/models/{slug}/endpoints` → per-provider serving info:
`provider_name` (OpenAI, Amazon Bedrock, …), `service_tier` (`flex`), `tag`,
`max_completion_tokens`, `max_prompt_tokens`, tiered `pricing.overrides`
(`min_prompt_tokens` → different price), `supported_parameters`, `supports_tool_choice`,
and `status: 0`. Verified live: `openai/gpt-6-astra` → 7 endpoints; `anthropic/claude-opus-5-5`
→ 11 endpoints. **This is the only source that shows which concrete providers serve a
model and at what tier price** — directly useful for a "backup provider" registry.

### A.5 Other sources

- **TrueFoundry models** (`truefoundry/models`, MIT, ★43, 27 providers, 1000+ models,
  one YAML per model): has **`isDeprecated: true`**, `canonical_model` (e.g.
  `anthropic/claude-3-5-haiku`), `external_ids`, `features[]`, `costs[]` with `region`,
  `params[]` with `maxValue`. Very close to the desired schema, but scoped to providers
  the TrueFoundry gateway supports.
- **OpenModels** (`openmodelsrun/openmodels`, ★8): the most rigorous *structure* —
  canonical `models/` separate from `providers/` separate from `mappings/` (provider↔model
  binding with pricing), all JSON-Schema-validated in CI, referential integrity enforced.
  This is the right **shape** even though the project is small. Its `mapping.schema.json`
  requires `model_id`, `provider_id`, `provider_model_name`, `pricing`, `rate_limits`,
  `available_regions`.
- **HuggingFace Hub** (`GET /api/models?full=true&config=true`): `id`, `author`,
  `createdAt`, `lastModified`, `gated`, `downloads`, `likes`, `library_name`,
  `pipeline_tag`, `tags[]`, `config` (architectures, model_type, quantization).
  **No context window, no pricing, no deprecation.** Its `tags[]` are free-form, so
  capability detection is unreliable. Use it only for open-weights lineage and as the
  `hugging_face_id` link that OpenRouter already carries.
- **AWS Bedrock `ListFoundationModels`**: returns `modelLifecycle` with
  `startOfLifeTime`, `legacyTime`, `endOfLifeTime`, `status` — **the only native provider
  lifecycle API.** The public endpoint 403s without auth; needs an AWS account.

### A.6 What actually detects deprecation, ranked

1. **models.dev `status`** — 893 deprecated models, provider-scoped, git-diffable.
   Best for *breadth* and for *diffing* (a new deprecation shows up as a git commit).
2. **LiteLLM `deprecation_date` + `source`** — best for *dates* and *provenance*.
3. **AWS Bedrock `modelLifecycle`** — best *authority* for Bedrock models.
4. **TrueFoundry `isDeprecated`** — good coverage (1000+ models), but gateway-scoped.
5. **OpenRouter `expiration_date`** — narrow (12 models) but precise for OR's own catalog.
6. **Absence from a provider's `/models` endpoint** — the universal fallback, and the only
   one that catches a provider that silently renames or drops a model. upb's `upb verify`
   already implements exactly this (`missing_upstream`).

**The rename-detection gap:** no source directly says "provider X renamed `foo` to `bar`".
It must be inferred by diffing consecutive snapshots of the same provider's model list,
or by using `canonical_model_id` (models.dev) / `canonical_slug` + `alias_target`
(OpenRouter) as the rename map.

### A.7 Validation against upb's real config

Ran provider-scoped lookups of upb's 38 declared `(provider, model)` pairs against
models.dev:

| result | count | meaning |
|---|---|---|
| `active` | 24 | model live at that provider |
| `deprecated` | 4 | **genuinely dead at that provider** |
| `model-not-at-provider` | 10 | id not served there (or provider unknown) |

The four real deprecations in upb's own config:

| provider | model | canonical |
|---|---|---|
| `alibaba-token-plan` | `qwen3.8-max-preview` | `alibaba/qwen3.8-max-preview` |
| `ollama-cloud` | `deepseek-v4-flash` | `deepseek/deepseek-v4-flash` |
| `ollama-cloud` | `glm-5.1` | `zhipuai/glm-5.1` |
| `ollama-cloud` | `qwen3.5:397b` | `alibaba/qwen3.5-397b-a17b` |

**A methodological trap found and rejected:** naive substring matching produced **25
false-positive "deprecated" hits** (e.g. `glm-5.2` matched `glm-5.2` at `dinference`
(deprecated) while it was `active` at `zai`). Any registry must key on the exact
`(provider, model_id)` pair and never fuzzy-match model names.

---

## Part B — Config snapshot / versioning / secrets

### B.1 What "what was I running at time T" requires

Three independent time axes, currently conflated:

1. **Config time** — which provider/model/key-slot was *declared*.
2. **Catalog time** — what the *provider's* catalog said at that moment.
3. **Secret time** — which *credential* was live (and which is now revoked).

A registry answers (2) and (1); git answers (1); the secret manager answers (3). You
need all three or the question "why did it cost $40 on the 3rd?" is unanswerable.

### B.2 Tooling survey

| Tool | Stars | Licence | Snapshot mechanism | Secret mechanism | Fit |
|---|---|---|---|---|---|
| **git** | — | — | commits, tags, `git log --since`, `git bisect` | n/a | **baseline**; gives time-travel for free |
| **chezmoi** | ★22,021 | MIT | source dir is a git repo; `chezmoi git log`, `chezmoi diff` | native **age** encryption (`chezmoi add --encrypt`), `bitwarden`/`pass`/`gopass` template funcs | **best fit for the whole config** |
| **SOPS** | ★23,485 | MPL-2.0 | `sops` in-place edits; `.gitattributes` `diff=sopsdiffer` decrypts diffs | age/PGP/KMS, **value-level** (keeps YAML structure visible) | best when secrets live *inside* a YAML you want to read |
| **age** | — | public domain | n/a | X25519 + ssh recipients | the modern default over PGP |
| **gitleaks** | ★30,240 | MIT | n/a | **detects** leaked secrets in git history/CI | guardrail, not storage |
| **1Password CLI** | — | proprietary | secret refs `op://vault/item/field` in any file | `op read` / `op run` / `op inject`; `op run` masks stdout/stderr | best for **rotating** provider keys |
| **Terraform / OpenTofu** | — | MPL-2.0/BUSL | `terraform state` + plan/apply history | **not a secret store** — needs a backend (Vault, S3+KMS) | good for *describing* key slots, bad for holding keys |
| **Nix / devenv** | — | LGPL/MIT | lockfiles pin exact versions | `sops`/`age` integrations; `nix flake` pins | best for **tooling** reproducibility, overkill for model ids |
| **VCS-friendly YAML registries** | — | — | `openmodelsrun/openmodels`, `truefoundry/models` | n/a (metadata only) | precedent for registry-as-repo |

**Findings:**

- **chezmoi + age is the best fit.** It solves "apply config" *and* "version config" *and*
  "encrypt secrets" in one tool, with git as the history backend. `chezmoi git log` gives
  the timeline; `chezmoi add --encrypt` protects secrets; `chezmoi diff` shows drift.
  SOPS is the better companion when secrets are *fields inside* the YAML you want to
  review (its `.gitattributes` filter makes `git diff` decrypt in place).
- **1Password secret references beat encrypted-at-rest files for rotating keys.** The
  registry can contain `op://personal/OPENROUTER_KEY_1/key` and the *value* rotates
  without touching git history. `op run -- cmd` injects and masks.
- **Terraform/OpenTofu is the wrong tool for key slots.** It describes infrastructure
  *resources*, and holds no secret material. For a personal setup, a declarative YAML
  `key_slots:` block plus 1Password references is simpler and does the same job.
  Terraform becomes worthwhile only if the keys are provisioned via a cloud KMS/IAM
  system, which is not the case for OpenAI/Anthropic-style console keys.
- **Nix/devenv** pins *binaries*, not *model ids*. Worth using for pinning the LiteLLM
  version (so the pricing JSON matches the gateway), but not for the registry itself.
- **gitleaks belongs in pre-commit + CI**, scanning both the config repo and any
  snapshot dir, so a leaked key never lands in history.

### B.3 A concrete snapshot design (fits upb)

```
~/.config/upb/
  routes.yaml                 # committed — the live route config (non-secret)
  registry/
    registry.yaml             # committed — THE model registry (see Part D)
    keys.yaml                 # committed — key SLOT declarations (refs only, no values)
    snapshots/
      2026-10-23.json         # committed — daily snapshot of registry + catalogs
      catalog-models-dev.json # committed — raw models.dev api.json (or a git submodule)
      catalog-litellm.json    # committed — raw LiteLLM pricing json
      catalog-openrouter.json # committed — raw OpenRouter models json
  secrets.env                 # NOT committed — real values, 0600
```

- `keys.yaml` holds only *slots*: `{slot: OPENROUTER_KEY_1, provider: openrouter, state: active,
  secret_ref: "op://personal/OPENROUTER_KEY_1/key"}`. Values live in 1Password or
  `secrets.env`. Git records the slot lifecycle (added/retired/rotated), never the value.
- `snapshots/YYYY-MM-DD.json` is written by a daily job and committed. It records the
  resolved registry state, the ETag/hash of each upstream catalog, and the *observed*
  provider `/models` listing per provider. This gives "what was I running at time T"
  even for models that vanished from every catalog.
- `upb verify` already does the live-catalog comparison (`missing_upstream` /
  `new_upstream`). Extend it to also report `deprecated_upstream` and
  `id_changed_upstream` using the registry.

---

## Part C — The real pain point: "providers change model ids all the time"

### C.1 Root cause

A provider's model id is **not a stable identifier**. It is a *routing label* the
provider happens to publish today, and it changes for at least five distinct reasons:

1. **Version pinning** — `claude-sonnet-4-5-20250929` → `claude-sonnet-5.5`.
2. **Alias pointer drift** — `claude-sonnet-latest` silently becomes a different model
   tomorrow. Your config is unchanged; your behaviour is not.
3. **Vendor re-skinning** — `gpt-4o` → `gpt-5.4-mini`; `glm-5.2` → `glm-5.3`.
4. **Gateway-specific names** — the same model is `claude-opus-5.5` at OpenRouter,
   `anthropic.claude-opus-5-5-v1:0` at Bedrock, `claude-opus-5-5` at Zen, and
   `claude-opus-5.5-20260921` on Bedrock's OpenRouter endpoint.
5. **Silent removal** — the id is gone; upstream returns 404 or 400 with no warning.

The *correct* framing: **you cannot pin a model id and expect it to mean the same thing
over time.** The things that are stable are (a) the *capability profile* — context
window, modality support, tool support, reasoning support; (b) the *family*; and
(c) the *provider's own alias pointer*, if the provider offers one.

### C.2 Projects that solve it

| Project | Stars | Approach |
|---|---|---|
| **OpenRouter `~provider/model-latest`** | — | Provider-published stable alias that re-points on upgrade. 19 live. The cheapest correct fix. |
| **LiteLLM model groups / `model_group_alias`** | ★61,857 | Config maps a stable group name → a list of concrete models with weights; router picks and falls back. Since v1.98, routing groups are callable virtual models and appear in `/v1/models`. |
| **LiteLLM `model_group_alias`** | — | Alias → concrete model, resolved before deployment lookup. ⚠️ Known sharp edge: an alias silently shadows a real model of the same name; and since v1.81.7 the proxy overwrites the response `model` field with the *requested* alias, losing the resolved deployment (open bug #22709). |
| **models.dev `canonical_model_id`** | ★7,353 | One canonical id (`zhipuai/glm-5.2`) across 89 providers; each provider maps its own local id → canonical. |
| **OpenRouter `canonical_slug`** | — | The dated/pinned id, plus `alias_target` for latest-pointers. |
| **vLLM Semantic Router** | ★6,247 | "One API for many models"; public model id `vllm-sr/auto`; selects among configured backends by policy (quality/latency/cost), local+cloud+private. |
| **OpenModels** | ★8 | Canonical model ↔ provider mapping with referential integrity enforced in CI. |
| **TrueFoundry models** | ★43 | `canonical_model` per provider entry, `isDeprecated`. |
| **role-model** | ★118 | An open *protocol* for capability-aware routing: request requirements, endpoint profiles, policy, and an explanation artifact. |
| **AGenNext/model-router** | ★0 | Declarative `config/models.yaml` with `capabilities: [chat, coding, reasoning, tools, json, long_context]`, context window, cost, quality/latency/reliability scores, fallback chains. |
| **veto** | ★2 | Deterministic capability+cost filters, then structured accept/reject admission from candidates. |
| **PrismoRouter** | — | Prompt complexity analysis → cheapest capable model; ported from vLLM SR. |
| **pai-llm-config** | — | One `llm-config.yaml` with semantic aliases (`smart`, `fast`, `cheap`), multi-key pool with rotation strategies, env/profile layering. |

### C.3 Capability-based vs model-id-based routing

Model-id routing is fragile because the id *is* the contract. Capability routing asks
"which model satisfies {tools, ≥200k context, vision, reasoning} at the lowest cost?" and
lets the answer change over time.

The `role-model` and `ai-orchestrator` designs are the most rigorous: they separate
(a) *what the request needs*, (b) *what each endpoint can do*, (c) *what policy allows*,
(d) *why the decision was made* — and require the router to produce an explanation
artifact. `ai-orchestrator` goes further: eligibility is checked **before** scoring,
inferred capability profiles are disabled by default, and it distinguishes maker/checker
identity separation.

For a personal setup, the pragmatic middle is:

1. **Keep model-id routing at the edges** (Claude Code sends `claude-opus-4-6`).
2. **Resolve that wire name through a local alias table** → one or more
   `(provider, model_id)` candidates.
3. **Filter candidates** by hard requirements (context ≥ needed, tools required, vision
   required) and by *liveness* (not deprecated at that provider, still in the provider's
   `/models`).
4. **Rank** by a declared preference order — this is where "active / backup / deprecated"
   maps directly.
5. **Record** the decision (which candidate, why, what the fallback chain was) so
   "what was I running at time T" is answerable from logs.

That is exactly the shape of upb's `routes.yaml` (`priority`, `enabled`, `trust_zone`,
`model_map`) plus the registry that this research defines.

### C.4 The three-layer answer (recommended)

```
 Layer 1  WIRE ALIAS      "claude-opus-4-6"         ← what your client asks for (stable, yours)
 Layer 2  INTENT SLOT     "primary.coding"          ← capability contract: tools, ctx, cost ceiling
 Layer 3  CONCRETE BINDING "ollama-cloud/glm-5.2"   ← (provider, model_id) — the ONLY churny layer
```

Only Layer 3 changes when a provider renames or sunsets a model. Layer 1 and 2 are
yours and stay stable. The registry's job is to keep Layer 3's *candidates* alive and
ranked, and to tell you when one dies.

---

## Part D — Recommended data schema

### D.1 Design constraints, derived from the measurements above

1. **Status is per `(provider, model_id)`** — 315 models differ by provider.
2. **Never fuzzy-match model ids** — substring matching produced 25 false positives.
3. **Separate the canonical model from the provider binding.** Canonical = identity;
   binding = where it is served and for how much.
4. **Provider namespaces differ per source** — LiteLLM matched only 15/38 of upb's ids
   under naive lookup. Every source reference needs its own namespace key.
5. **Deprecation dates need provenance** — LiteLLM's bulk dates (49 on one day, 81
   Bedrock entries on `2027-03-30`) are not per-model sunsets. Store the `source` URL.
6. **Keep secrets out.** The registry references key slots; it never holds values.
7. **Snapshot, don't scrape.** Store the raw upstream payloads too — they are the
   evidence for every derived field.

### D.2 The schema

```yaml
# registry.yaml — canonical, provider-agnostic model registry
schema_version: 1
generated_at: 2026-10-23T00:00:00Z

# ── Providers ──────────────────────────────────────────────────────────────
providers:
  ollama-cloud:
    display_name: Ollama Cloud
    kind: gateway            # first_party | gateway | aggregator | local | subscription
    models_dev_id: ollama-cloud
    litellm_id: null         # LiteLLM has no ollama-cloud namespace
    openrouter_id: null
    base_url: https://ollama.com/v1
    auth:
      type: envfile          # env | envfile | keychain | op_ref | none
      path: ~/.hermes/.env
      var: OLLAMA_API_KEY
    key_slots: [OLLAMA_PRIMARY, OLLAMA_BACKUP]
    trust_zone: remote-approved
    status: active

# ── Canonical models (identity, independent of any provider) ───────────────
models:
  zhipuai/glm-5.2:
    display_name: GLM 5.2
    family: glm-5.2
    vendor: zhipuai
    release_date: 2026-01-20
    open_weights: true
    modalities:
      input: [text, image]
      output: [text]
    capabilities:
      tools: true
      reasoning: true
      structured_output: true
      attachment: true
      temperature: true
    context_window: 204800
    max_output_tokens: 131072
    aliases: [glm-5.2, glm-5-2]

# ── Bindings: where a canonical model is served ───────────────────────────
bindings:
  ollama-cloud/glm-5.2:
    provider: ollama-cloud
    model_id: glm-5.2
    canonical: zhipuai/glm-5.2
    status: deprecated          # active | backup | deprecated | unknown
    status_source: models.dev   # models.dev | litellm | provider_api | manual | observed
    status_checked_at: 2026-10-23
    deprecation_date: null      # ISO date, only when a dated source asserts one
    deprecation_source: null    # URL justifying deprecation_date
    superseded_by: zhipuai/glm-5.3
    price:
      input_per_1m: 0.60
      output_per_1m: 2.20
      cache_read_per_1m: 0.06
      source: models.dev
    observed:
      in_provider_catalog: true
      last_seen_at: 2026-10-23
      renamed_to: null          # filled when id changes at this provider
    notes: ""

# ── Intent slots (capability contracts) — the routing target ──────────────
slots:
  primary.coding:
    require: { tools: true, context_window_min: 200000, reasoning: true }
    cost_ceiling_per_1m: 5.00
    prefer: [zai/glm-5.2, ollama-cloud/glm-5.2, deepseek/deepseek-v4-pro]
    fallback: [zai/glm-5-turbo, ollama-cloud/glm-5.1]
    bind_to: ollama-cloud/glm-5.2     # the currently-selected concrete binding
    status: active                      # active | backup | deprecated
```

### D.3 Field provenance — where each field comes from

| Field | Primary source | Fallback | Notes |
|---|---|---|---|
| `canonical` (id) | models.dev `canonical_model_id` | OpenRouter `canonical_slug` | Strip the provider prefix → `zhipuai/glm-5.2`. models.dev: 7,548/8,849 entries carry it. |
| `provider` / `model_id` | models.dev provider key + model key | LiteLLM key prefix, OpenRouter `id` | Provider-scoped id — the only id that is churny. |
| `status` | models.dev `status` | TrueFoundry `isDeprecated`; provider API; manual | **Per binding, not per model.** models.dev has no date for `deprecated` — only LiteLLM/AWS/TrueFoundry do. |
| `deprecation_date` | LiteLLM `deprecation_date` | AWS Bedrock `modelLifecycle.endOfLifeTime` | Always store the paired `deprecation_source` URL. |
| `deprecation_source` | LiteLLM `source` | manual URL | 731/866 LiteLLM deprecations have one. |
| `release_date` | models.dev `release_date` | OpenRouter `created` (epoch); HF `createdAt` | |
| `context_window` | models.dev `limit.context` | LiteLLM `max_input_tokens`; OpenRouter `context_length` | models.dev: present on 8,849/8,849. |
| `max_output_tokens` | models.dev `limit.output` | LiteLLM `max_output_tokens`; OpenRouter `top_provider.max_completion_tokens` | |
| `price.input/output` | models.dev `cost.input/output` | LiteLLM `input_cost_per_token`; OpenRouter `pricing.prompt/completion` | models.dev is per-1M; LiteLLM per-token; OpenRouter per-token. **Normalize to per-1M.** |
| `price.cache_read` | models.dev `cost.cache_read` | LiteLLM `cache_read_input_token_cost`; OpenRouter `pricing.input_cache_read` | |
| `capabilities.tools` | models.dev `tool_call` | LiteLLM `supports_function_calling`; OpenRouter `supported_parameters` ∋ `tools` | |
| `capabilities.reasoning` | models.dev `reasoning` | LiteLLM `supports_reasoning`; OpenRouter `reasoning` / `supported_parameters` ∋ `reasoning` | |
| `capabilities.structured_output` | models.dev `structured_output` | LiteLLM `supports_native_structured_output`; OpenRouter `structured_outputs` | |
| `modalities` | models.dev `modalities.input/output` | OpenRouter `architecture.input_modalities`; LiteLLM `supported_modalities` | |
| `open_weights` | models.dev `open_weights` | HF presence of `safetensors` | |
| `hugging_face_id` | OpenRouter `hugging_face_id` | HF `id` | OpenWeights lineage. |
| `superseded_by` | manual / diff of consecutive snapshots | OpenRouter `alias_target` | **No source states this directly.** Derive it. |
| `renamed_to` | diff of consecutive provider `/models` snapshots | — | Derived, not fetched. |
| `in_provider_catalog` | live `GET {base_url}/models` | — | upb `upb verify` already does this. **The universal liveness check.** |
| `last_seen_at` | observation | — | Set every time a live probe succeeds. |
| `key_slots` | your config | — | Slot *names* only; no values. |
| `secret_ref` | 1Password `op://…` | age-encrypted file | Values never enter git. |

### D.4 Field rules (enforced by a validator)

```
1. status ∈ {active, backup, deprecated, unknown}
2. status ∈ {deprecated} ⇒ status_source ≠ manual, or deprecation_source is set
3. status == deprecated ⇒ deprecated_at is set (date the registry noticed)
4. deprecation_date present ⇒ deprecation_source present (no unsourced dates)
5. binding.provider + binding.model_id is unique (exact match, never fuzzy)
6. binding.canonical must exist in models{}
7. slot.bind_to must reference an existing binding{}
8. slot.require.* must be satisfiable by every model in slot.prefer
9. no secret material: reject any value matching /sk-[A-Za-z0-9]{20,}/ or similar
10. every binding has status_checked_at; stale (> 7d) ⇒ status: unknown
```

### D.5 Source precedence for conflict resolution

```
status:        provider live /models  >  models.dev  >  TrueFoundry  >  LiteLLM  >  manual
deprecation:   AWS modelLifecycle  >  LiteLLM+source  >  TrueFoundry  >  OpenRouter expiration_date
pricing:       provider pricing API  >  models.dev  >  LiteLLM  >  OpenRouter
capabilities:  models.dev  ≈  LiteLLM  (prefer models.dev; LiteLLM has more flags)
```

When two sources disagree on `status`, record **both** and prefer the provider's own
catalogue — a provider that still serves a model is the ground truth, and a stale
community catalog is the usual cause of false "deprecated".

### D.6 Migration path from the current upb config

upb's `routes.yaml` already holds `providers.*.models` with `port` and `pricing`. The
registry is a **superset** of that, so migration is additive:

1. **Extract** `routes.yaml` → `registry.yaml` (providers, bindings, slots).
   `pricing.input_per_1m` → `price.input_per_1m`; `port` stays on the provider.
2. **Add** `canonical` per model — resolve via models.dev `canonical_model_id`.
3. **Add** `status` — run the models.dev provider-scoped lookup for each binding.
   Expect ~4 `deprecated` among upb's 38 today, plus ~10 `model-not-at-provider`
   that need a manual decision (are they custom gateway aliases like
   `ornith-9b`/`amalia-9b`, or genuinely gone?).
4. **Add** `key_slots` — `routes.yaml` already has `key: {type: env, var: X}`;
   convert to slot names + 1Password refs.
5. **Extend `upb verify`** (cli/upb:885) with `deprecated_upstream` and
   `id_changed_upstream`, using the registry as the reference rather than only
   diffing against the live catalog.
6. **Add** `upb snapshot` — writes `snapshots/YYYY-MM-DD.json` (registry state +
   catalog ETags + observed provider listings) and commits it.

### D.7 Worked example — the same model at three providers

```yaml
models:
  zhipuai/glm-5.2: {display_name: GLM 5.2, family: glm-5.2, release_date: 2026-01-20, ...}

bindings:
  zai/glm-5.2:
    provider: zai
    model_id: glm-5.2
    canonical: zhipuai/glm-5.2
    status: active
    status_source: models.dev
    price: {input_per_1m: 0.60, output_per_1m: 2.20, source: models.dev}
  alibaba-token-plan/glm-5.2:
    provider: alibaba-token-plan
    model_id: glm-5.2
    canonical: zhipuai/glm-5.2
    status: active
    status_source: models.dev
  dinference/glm-5.2:
    provider: dinference
    model_id: glm-5.2
    canonical: zhipuai/glm-5.2
    status: deprecated
    status_source: models.dev
    status_checked_at: 2026-10-23
```

One canonical model, three bindings, three independent statuses. A model-id-keyed
registry would have forced one of these to be wrong.

### Measurement provenance

All figures were measured against the live APIs on **2026-10-23** and cross-checked
against the local Hermes cache (`~/.hermes/models_dev_cache.json`, a snapshot of
`https://models.dev/api.json`). Where the two differ, the **live** numbers are quoted
here (the cache is a slightly older snapshot; e.g. canonical-model count 619 live vs
629 cached, mixed-status count 315 live vs 374 cached). The catalog changes daily —
expect these numbers to drift, and treat the *method*, not the counts, as the durable
result.

---

## Appendix A — Verified project references

| Project | URL | Licence | Stars | Role |
|---|---|---|---|---|
| models.dev | https://github.com/anomalyco/models.dev | MIT | 7,353 | **primary catalog**; `https://models.dev/api.json` |
| LiteLLM | https://github.com/BerriAI/litellm | MIT-ish | 61,857 | `model_prices_and_context_window.json` |
| OpenRouter API | https://openrouter.ai/docs/api-reference/list-available-models | public API | — | `canonical_slug`, `alias_target`, `expiration_date` |
| TrueFoundry models | https://github.com/truefoundry/models | MIT | 43 | `isDeprecated`, `canonical_model` |
| OpenModels | https://github.com/openmodelsrun/openmodels | — | 8 | canonical↔provider mapping + JSON Schema CI |
| vLLM Semantic Router | https://github.com/vllm-project/semantic-router | Apache-2.0 | 6,247 | capability routing |
| role-model | https://github.com/try-works/role-model | — | 118 | capability-routing protocol |
| vLLM SR routing docs | https://docs.vllm.ai/ | — | — | `vllm-sr/auto` public model id |
| LiteLLM routing | https://docs.litellm.ai/docs/routing | — | — | routing groups, `model_group_alias` |
| Cline catalog | https://github.com/cline/cline/blob/main/sdk/packages/llms/src/catalog/README.md | Apache-2.0 | — | consumes models.dev; documents token-limit semantics |
| Cline model docs | https://docs.cline.bot/api/models | — | — | OpenRouter-style `provider/model` ids |
| chezmoi | https://github.com/twpayne/chezmoi | MIT | 22,021 | config as code + age encryption |
| SOPS | https://github.com/getsops/sops | MPL-2.0 | 23,485 | value-level secret encryption |
| gitleaks | https://github.com/gitleaks/gitleaks | MIT | 30,240 | secret leak detection |
| 1Password CLI | https://developer.1password.com/docs/cli/secret-reference-syntax | proprietary | — | `op://` secret references |
| pai-llm-config | https://github.com/HuangZurong/pai-llm-config | MIT | 1 | semantic aliases + multi-key rotation |
| llm-registry | https://github.com/yamanahlawat/llm-registry | MIT | 18 | capability registry, local storage |
| AWS Bedrock API | https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModels.html | — | — | `modelLifecycle` |
| LiteLLM issue #22709 | https://github.com/BerriAI/litellm/issues/22709 | — | — | alias shadowing + response `model` regression |
| LiteLLM PR #36519 | https://github.com/BerriAI/litellm/pull/36519 | — | — | routing groups as callable virtual models |
| upb (local) | https://github.com/fabiofalopes/upb | — | — | router; `upb verify` at `cli/upb:885` |

## Appendix B — Reproduction commands

```bash
# models.dev (live)
curl -s https://models.dev/api.json | jq '[.openrouter.models[] | select(.status=="deprecated")] | length'   # -> 18

# models.dev git time machine
git clone --filter=blob:none https://github.com/anomalyco/models.dev
git -C models.dev log --since=2026-06-01 --oneline -- providers/zai/models/

# LiteLLM deprecations
curl -sL https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json \
  | jq '[to_entries[] | select(.value.deprecation_date != null and (.value.deprecation_date|startswith("20")))] | length'

# OpenRouter aliases + expiry
curl -s https://openrouter.ai/api/v1/models | jq '[.data[] | select(.alias_target!=null)] | length'
curl -s https://openrouter.ai/api/v1/models | jq '[.data[] | select(.expiration_date!=null)] | length'

# OpenRouter per-provider endpoints (which providers serve a model)
curl -s https://openrouter.ai/api/v1/models/anthropic/claude-opus-5-5/endpoints | jq '.data.endpoints | length'

# HuggingFace (no pricing/deprecation available)
curl -s "https://huggingface.co/api/models?limit=1&full=true&config=true" | jq '.[0] | keys'
```

## Appendix C — Open questions

- **Do upb's gateway-only models (`ornith-9b`, `amalia-9b`, `omnicoder-9b`) need registry
  entries?** They are not in models.dev or LiteLLM. The WORKLOG notes the Lusófona gateway
  itself aliases `ornith-9b` → `bonsai-27b-1bit` — i.e. **the churn is inside the
  provider**, invisible from outside. Such models need a `status_source: manual` +
  `observed` treatment, and the registry should record the *upstream* alias once confirmed.
- **Is `qwen3.8-max-preview` (deprecated at `alibaba-token-plan`) intentionally declared?**
  routes.yaml lists it with an `active_until: '2026-08-20'` — a date already past. Probably
  a cleanup candidate → `status: deprecated`.
- **Should `deepseek-v4-flash` at `ollama-cloud` be demoted to `backup`?** It is deprecated
  upstream but upb may still want it as a fallback. This is exactly the
  active/backup/deprecated distinction the registry encodes.
- **`zen` is absent from models.dev.** Zen's free-tier rotation
  (`big-pickle`, `north-mini-code-free`) is the highest-churn surface in upb — 2 of 3
  Zen models are already `deprecated` upstream. This surface needs live-observation-only
  tracking (`upb sync`/`discover` + snapshots), since no static catalog covers it.