# Migration from Panopticon — Gap Analysis & Plan

**Date:** 2026-08-17 · **Method:** full working-tree read of both repos, git archaeology, live-runtime inspection (Docker/Postgres/Redis/logs), background capability inventories.
**Scope:** review of `upb` (`e360cf5`) and `panopticon` (`ebe6024`).
**Execution status:** P0 done 2026-08-17 — `future/` committed to panopticon (`c2ef3f3`, pushed) and vendored to `docs/reference/panopticon-future/`. P1-P3 implemented 2026-08-17 (pricing + `cost_usd`, provider cooldown/failover + first test suite, custom headers + Mistral provider) — see WORKLOG session log; pending Linux-box deploy + live validation. P4 skipped (optional). P5 done 2026-08-17 — stack stopped (`docker compose down`, volumes kept), tag `archive-2026-08` pushed, GitHub description set to archived/superseded-by-upb. Late finding: one live consumer remained — a Go OpenAI-SDK client on the Mac called `codestral` via :4000 on 2026-08-16 ($0.0029); identify before it next needs an LLM. Mistral Vibe plan confirmed alive by that call.

---

## 1. Executive summary

- **The task premise is wrong in one important way:** upb contains **no Langfuse integration** — zero matches across the working tree and git history, local `main` == `origin/main` == `e360cf5` (verified via `git rev-parse` + GitHub). Langfuse lives in **panopticon** (`config.yaml:257`), and upb does **not** route through panopticon: upb's `litellm` provider points at the Lusófona university gateway (`config/routes.yaml.example:84-88`), not `localhost:4000`. Whatever "upb integrated Langfuse" meant, the repos are fully decoupled in production.
- **Panopticon is live but idle:** all 6 containers up since 2026-08-10 on this Mac, yet **0 requests in 96h** (LiteLLM logs), **0 SpendLogs rows**, **0 Langfuse traces/observations/scores/datasets/prompts**, **empty Redis keyspace**. The observability plane it exists to provide is consuming resources and producing nothing.
- **What panopticon still holds that matters:** (1) per-model **pricing tables** — upb tracks tokens but no dollars; (2) the **provider-cooldown concept** in untracked `future/custom_routing/tier_router.py:19-22,127-128` — upb's only defense against 429s is per-request retry (`router/src/utils/errors.ts:36-40`) while Zen has 11h cooldowns and Alibaba a weekly quota (`upb/WORKLOG.md:58`); (3) the **Mistral Vibe plan wiring** (`config.yaml:79-159`) — 7 models, subscription auth + UA trick, existing nowhere else.
- **Top 3 migration priorities:** cost-aware usage tracking (S), provider cooldown/quarantine (S-M), Mistral Vibe provider (S-M, needs a small `headers:` feature in routes.yaml).
- **Langfuse verdict: TRIM** — retire with panopticon, do not port. Everything it offers is empirically unused (all DB counts zero); replace its one valuable function, cost visibility, with in-router cost computation. If prompt-level tracing is ever needed again, right-size per your own landscape research (Phoenix, single container ~500MB — `llm-stack-landscape-2026.md:139`).
- **Urgent housekeeping:** `future/` — the **only surviving copy** of the archived-and-deleted `ai-model-router` code — is **untracked** (`git ls-files future/` → 0). Commit it before anything else.

---

## 2. Repo profiles

### upb — canonical, actively developed

A personal infrastructure tool that makes Claude Code (and any Anthropic- or OpenAI-speaking client) provider-agnostic: a **dual-intake translation proxy** (Anthropic Messages ⇄ OpenAI Chat Completions, incl. streaming SSE), a **route-control CLI** (`list/status/run/stop/default/doctor/models/sync/env`), and a **key pipeline** (`upb sync` harvests keys from OpenCode `auth.json`/`opencode.json`/env → `secrets.env` → `router.env`). TS router + Python CLI, zero runtime deps beyond `yaml`, deployed on a Linux box under systemd (`WORKLOG.md:67-73`); this Mac is only a checkout (`~/.config/upb` does not exist here — verified).

- 8 commits, 2026-08-06 → 2026-08-07, pushed to github.com/fabiofalopes/upb.
- Strengths: protocol translation with claude-* model maps (`router/src/index.ts:40-102`), tool-call-streaming assembly (`router/src/utils/stream.ts:216-276`), retryable-error classification (`router/src/utils/errors.ts:10-28`), session-model binding (`cli/upb:422-442`, `scripts/claude-wrapper`), self-reproducing idempotent installer (`scripts/install.sh`), model discovery for rotating catalogs (`cli/upb:817-865`), JSONL usage log + aggregate endpoint (`router/src/utils/usage-logger.ts:18-25`, `router/src/index.ts:687-734`).
- Gaps: **no tests, no CI, no linting** (verified — none exist); usage tracking is token-only, **no cost**; no cross-request rate-limit memory.
- No TODO/FIXME/HACK comments anywhere (verified by grep).

### panopticon — legacy predecessor, live but trafficless

A Docker-Compose "personal LLM control plane": LiteLLM gateway (:4000) + Langfuse (:3000) + Redis cache + 2× Postgres + CLIProxyAPI OAuth bridge (:8317, localhost-only) — `docker-compose.yml:1-98`. The idea: point every tool (Fabric, scripts, agents) at one OpenAI-compatible endpoint and observe everything.

- 2 commits, both 2026-07-21 (`f67088b`, `ebe6024`), pushed to github.com/fabiofalopes/panopticon (`git ls-remote` == local HEAD). Working tree clean **except untracked `future/`**.
- 22 active model entries across 5 providers: ULusofona ×3, Alibaba Token Plan ×6, **Mistral Vibe ×7**, Zen free ×5, CLIProxyAPI ×1 (`config.yaml:3-253`). Notably, the Mistral Vibe section was the **last work done** — `HANDOFF.md` (same day) still says "15 active models" and lists `MISTRAL_API_KEY` as unmapped (`HANDOFF.md:58,154`), i.e. config ran ahead of docs right before the project went quiet.
- It **worked** once: verified test calls with traces and real-dollar spend are documented (`HANDOFF.md:107-116`).
- It works **no longer**: stack restarted 2026-08-10 (container `StartedAt`), and since then 0 POST requests in LiteLLM logs, all five observability tables at 0, Redis keyspace empty (all verified live on 2026-08-17). The Jul 20-21 traces/spend rows are gone — volumes were wiped or recreated at some point (see Open Questions #1). The transition is dated: upb was built Aug 6 (`WORKLOG.md:38-39`), panopticon's last documented traffic is Aug 6 via the Lusófona gateway, not the local stack (`WORKLOG.md:57`).
- `WORKSPACE_AUDIT.md:15` (Jul 23) still calls it "infrastructure you run daily" — that claim is now stale.

**No contradiction with the Context section beyond the Langfuse premise** (corrected in §1): panopticon is indeed the legacy predecessor, and it is "largely obsolete" in utilization terms — but it is not inert: it runs, and it holds the only copies of several assets listed in §4.

---

## 3. Parity matrix

| Capability | upb | panopticon | Evidence |
|---|:---:|:---:|---|
| Anthropic⇄OpenAI translation (incl. SSE, tools, thinking-block stripping) | ✅ | ❌ | upb: `router/src/utils/translate.ts:32-331`, `stream.ts:69-335`; pan: OpenAI-intake only, no claude-* maps anywhere in `config.yaml` |
| Claude Code takeover (settings merge, wrapper, session binding) | ✅ | ❌ | upb: `scripts/install.sh:349-376`, `scripts/claude-wrapper:20-30`, `cli/upb:422-442` |
| Route-control CLI | ✅ | ❌ | upb: `cli/upb` (1019 lines, 9 subcommands); pan: none |
| Self-reproducing installer / uninstaller | ✅ | 🟡 | upb: `scripts/install.sh` (419 ln, idempotent, --dry-run); pan: `start.sh` bootstrap only |
| Key pipeline (harvest → secrets.env → router.env) | ✅ | 🟡 | upb: `cli/upb:867-968` (OpenCode auth.json etc.); pan: `secrets` tool + `start.sh:31-45` .env gen |
| Model discovery (rotating catalogs) | ✅ | ❌ | upb: `cli/upb:817-865`, `routes.yaml.example:74-76` |
| Token usage tracking | ✅ | ✅ | upb: JSONL + `GET /usage` (`index.ts:687-734`); pan: Postgres SpendLogs + `/global/spend` (README:194) — **but 0 rows today** |
| **Cost ($ ) tracking** | ❌ | ✅ | pan: `model_info` pricing all Alibaba+Mistral models (`config.yaml:30-159`); upb: tokens only |
| **Full prompt/response tracing + UI** | ❌ | ✅ | pan: Langfuse (`config.yaml:257`, compose:52-67) — **0 traces today** |
| Response caching | ❌ | ✅ | pan: Redis (`config.yaml:258-262`) — **empty keyspace today** |
| Retry on transient errors | ✅ | 🟡 | upb: backoff+jitter (`errors.ts:36-40`); pan: whatever LiteLLM core does, unconfigured |
| **Provider cooldown / quarantine** | 🟡 | 🟡 | upb: per-request retry only; pan: `TierAwareRouter` written, **never wired** (`future/custom_routing/tier_router.py:19-22`) |
| **Benchmark-driven model selection** | ❌ | 🟡 | pan: `BenchmarkLoader` **never wired** (`future/custom_routing/benchmark_loader.py:58-154`); or-bench data exists (7 runs, `~/.cache/or-bench/`) |
| Request normalization hooks | ✅ | 🟡 | upb: adapter transforms (`adapters/types.ts:4-24`, thinking/cache_control stripping `translate.ts:73-102`); pan: `custom_hooks.py` written, **never wired** (README:166) |
| Proxy auth | ✅ | ✅ | upb: LOCAL_SECRET (`middleware/auth.ts:11-45`); pan: master key (`config.yaml:265`) |
| Health/readiness + doctor | ✅ | ✅ | upb: `/health` (`index.ts:156-170`), `upb doctor` (`cli/upb:716-790`); pan: readiness endpoint + compose healthchecks |
| Prometheus metrics | ❌ | ✅ | pan: `/metrics` (README:202) — no consumer exists |
| Provider: Alibaba Token Plan | ✅ | ✅ | both (upb `routes.yaml.example:15-42`, pan `config.yaml:21-77`) |
| Provider: OpenCode Zen | ✅ | ✅ | both (upb `routes.yaml.example:64-83`, pan `config.yaml:161-195`) |
| Provider: Z.AI / DeepSeek **native Anthropic** | ✅ | ❌ | upb `routes.yaml.example:43-63,130-153`; pan reaches them only via DashScope at 4-6× markup (HANDOFF:103) |
| Provider: LiteLLM gateway (as backend) | ✅ | — | upb `routes.yaml.example:84-100` (Lusófona gateway); pan **is** the LiteLLM |
| Provider: ULusofona (modelos.ai) | 🟡 | ✅ | upb: ornith+omnicoder via `litellm` provider; pan: direct + `amalia-9b` (`config.yaml:3-19`) |
| **Provider: Mistral Vibe plan** | ❌ | ✅ | pan `config.yaml:79-159` (7 models, Vibe UA header, pricing); upb: none (Ollama-Cloud `mistral-large-3` is a different route, `routes.yaml.example:198-199`) |
| Provider: Ollama | ✅ | 🟡 | upb: `routes.yaml.example:154-207`; pan: commented stub (`config.yaml:210-214`) |
| Provider: PrimeIntellect | ✅ | ❌ | upb `routes.yaml.example:101-129` |
| OAuth subscription bridge (CLIProxyAPI) | ❌ | 🟡 | pan `docker-compose.yml:41-50` — deployed, tested once (HANDOFF:96), **`cliproxy-auths/` empty** (verified: no files) |
| Process supervision | ✅ | ✅ | upb: systemd unit (`config/universal-router.service.example`); pan: docker `restart: unless-stopped` |
| Tests / CI / linting | ❌ | ❌ | neither (verified) |
| Docs + multi-session coordination | ✅ | ✅ | upb: README/ARCHITECTURE/SETUP/WORKLOG; pan: README/HANDOFF |

---

## 4. Gap analysis

Items where panopticon holds something upb lacks (including unwired/history-only finds). Effort: S <½ day, M 1-3 days, L >3 days.

| # | Item | Verdict | Value | Effort | Fit | Risk | Evidence |
|---|---|---|---|---|---|---|---|
| G1 | **Per-model pricing metadata + $-computed usage** — `model_info` input/output costs for all Alibaba/Mistral models, promo annotations | **MIGRATE** | High — upb's stated goal is "evaluating which provider earns its keep" (README:118-130), unanswerable in dollars today; DashScope-vs-direct 4-6× markup decisions need it (HANDOFF:103) | S | High — data lands in `routes.yaml`, math in `usage-logger.ts`, zero new services | Low | pan `config.yaml:30-159`; upb `usage-logger.ts:18-25` |
| G2 | **Provider cooldown/quarantine on 429/5xx** — `TierAwareRouter`'s cooldown map (`provider_cooldowns`, 5-min TTL) | **ADAPT** | High — Zen 11h cooldowns (pan `config.yaml:164`), Alibaba weekly quota (upb WORKLOG:58); upb currently just retries into the wall per request (`errors.ts:36-40`) | S-M | High — in-router state + `/health` exposure matches existing patterns | Low | `future/custom_routing/tier_router.py:19-22,64-73,127-128`; upb `errors.ts:10-28` |
| G3 | **Mistral Vibe plan provider** — 7 models, `api.mistral.ai/v1`, `User-Agent: mistral-client-python/Mistral-Vibe/2.21.0` spoof, pricing | **ADAPT** | Med-High — a paid sub sitting idle since Jul 21; cheapest small-model tier in the fleet (`mistral-small` $0.15/$0.60, `config.yaml:113-115`) | S-M | Med — upb routes.yaml has **no per-provider `headers:` field** (verified, absent from `routes.yaml.example`); adapter layer already supports `extraHeaders` (`adapters/types.ts:4-24`) so it's a small config-plumbing feature, not a redesign | Low | pan `config.yaml:79-159`; upb `adapters/types.ts`, `routes.yaml.example` |
| G4 | **Benchmark-driven model selection** — `BenchmarkLoader` over or-bench JSON (rankings by TPS/TTFB, auto opus/sonnet/haiku tier maps) | **REVIVE** | Med — upb exists for A/B provider evaluation (README:12-14, 29-30); or-bench is installed next door (`hub/or-bench/`) with 7 cached runs (Feb-Apr 2026); loader is the only surviving consumer code | M | Med — or-bench targets OpenRouter free models; needs generalizing to upb's providers or replaced by an `upb bench` that reuses the JSON schema | Low | `future/custom_routing/benchmark_loader.py:58-154`; `~/.cache/or-bench/*.json` (7 files, verified) |
| G5 | Langfuse tracing platform (2 containers + Postgres) | **OBSOLETE** | Empirically zero: 0 traces/observations/scores/dataset_items/prompts (verified via psql 2026-08-17); upb traffic never transits it | — | — | High if kept — ~4GB-class footprint (`llm-stack-landscape-2026.md:138`), pinned old major `langfuse/langfuse:2` (`docker-compose.yml:53`), dev-default secrets (compose:60-61) | pan `config.yaml:257`, `docker-compose.yml:52-67` |
| G6 | Redis response caching | **OBSOLETE** | Keyspace empty despite 4 days uptime (verified) — coding-agent traffic is unique-context; hit rate ≈ 0 by construction | — | — | — | pan `config.yaml:258-262` |
| G7 | CLIProxyAPI OAuth subscription bridge | **OBSOLETE** | `cliproxy-auths/` empty — **no subscription was ever added** (verified: no files); ToS-ban risk documented by the author himself (README:153-155, HANDOFF:132-136) | — | — | Account-ban risk if ever used | pan `docker-compose.yml:41-50`, README:106-155 |
| G8 | `custom_hooks.py` MessageFixHook (system→user role fix) | **OBSOLETE** | Superseded by env-var approach (README:166); upb's adapter transforms already normalize requests (`translate.ts:73-102`) | — | — | — | pan `custom_hooks.py:15-25` |
| G9 | LiteLLM spend DB/UI + Prometheus `/metrics` | **OBSOLETE** | G1 covers the need without a database service; no metrics consumer exists for one user | — | — | — | pan README:190-207 |
| G10 | ULusofona direct provider entries (incl. `amalia-9b`) | **MIGRATE** (partial) | Low-Med — only `amalia-9b` is missing from upb; ornith/omnicoder already routed via the `litellm` provider | XS | High | Low | pan `config.yaml:3-19`; upb `routes.yaml.example:96-100` |
| G11 | Ops knowledge: promo end-dates (P8), DashScope markup notes, port/IPv6 gotchas | **MIGRATE** | Med — real money decisions; lives only in pan HANDOFF | XS | High (docs/WORKLOG) | Low | pan HANDOFF:88-104,161-164 |

---

## 5. LLMOps recommendations

### 5.1 Langfuse evaluation

**What it is demonstrably being used for: nothing.** Runtime evidence (2026-08-17): all five Langfuse tables at 0 rows; LiteLLM SpendLogs at 0 rows; 0 POST requests in the proxy logs across the entire current uptime (since 2026-08-10); Redis keyspace empty. The callback *initializes* (`Initialized Success Callbacks - ['langfuse']` in container logs — the only Langfuse "activity" left). Historical value is real but modest: one documented session of test traces and a $0.004 spend verification (HANDOFF:111-115), data that no longer exists on disk.

**What it provides that goes unused: everything** — prompt management, datasets, evals, scores, sessions all at permanent zero. That's not surprising: panopticon is single-user gateway infrastructure, not an LLM application, and the workflow that would consume those features (curating datasets, scoring runs) doesn't exist in this ecosystem.

**Complexity cost it charges anyway:** 2 of 6 containers, a second Postgres, 2 secrets, LiteLLM startup coupling (`docker-compose.yml:87-91`), an aging pinned major (`langfuse/langfuse:2`), and the quiet failure mode you're looking at right now — a running, "healthy" observability plane observing nothing.

**Verdict: TRIM.** Do not port to upb; retire with panopticon (§7). upb's architecture (direct-to-provider, zero attached services, JSONL usage log) is philosophically opposite to Langfuse's, and upb already owns the lightweight end of the observability spectrum (`/usage`). The one Langfuse function worth keeping — **cost visibility** — is exactly G1, portable as data, not as a platform. Your own 2026-07 landscape research prescribed a phased adoption whose Phase 3 ("when you need full observability") was skipped straight to; the utilization data now says roll back to Phase 1 semantics (`llm-stack-landscape-2026.md:144-151`). If prompt-level trace debugging becomes a real need later, the right-sized reopen is Phoenix (~500MB, single container, `landscape:139`) — decide then.

### 5.2 Adjacent capabilities (only needs visible in the codebase)

| Need (with evidence) | Recommendation | Candidates & cost |
|---|---|---|
| **Cost tracking** — "which provider earns its keep" (upb README:118-130); 4-6× markup decisions (HANDOFF:103) | G1: pricing table in `routes.yaml` + cost fields in `usage-logger.ts` + $ totals in `GET /usage` | In-house, **S**. Rejected: LiteLLM spend DB (adds a service), Langfuse cost (G5) |
| **Rate-limit awareness** — Zen ~11h cooldowns (`config.yaml:164`), Alibaba weekly quota (WORKLOG:58), retry-storm risk (`errors.ts:36-40`) | G2: per-provider quarantine TTL in the router, surfaced in `/health` + `upb status`; Zen-aware longer TTLs | In-house ADAPT of `tier_router.py` concept, **S-M**. Rejected: LiteLLM router cooldowns (service) |
| **Quota/balance monitoring** — Alibaba has no usage API; cookie-console spec drafted (WORKLOG:27, planned `upb usage`) | Build on G1's log; keep the existing cookie-spec plan; no external tool | In-house, **M** (already scoped by author) |
| **Model evaluation for routing** — upb's raison d'être is provider A/B (README:12-14); or-bench + 7 cached runs exist locally | G4: `upb bench` (or generalize `BenchmarkLoader`) → tier maps → inform `upb default` | In-house REVIVE, **M**, optional after G1-G3 |
| Prompt versioning / datasets / eval frameworks / guardrails / OTel interop / gateway replacement | **Not recommended** — no consuming workflow exists anywhere in evidence (Langfuse counts: prompts 0, datasets 0, scores 0; no OTel collector; upb *is* the gateway). Revisit only if an actual LLM application enters the hub | — |

---

## 6. Phased migration plan

Ordered by value/effort; each step independently shippable. All upb work happens in the repo, then deploys to the Linux box per existing workflow (WORKLOG:18).

| Phase | Work | Effort | Validation criterion ("how we know the port worked") |
|---|---|---|---|
| **P0 — Preserve** (do first, today) | Commit `future/` to panopticon and push (it's untracked; source project `~/projetos/ai-model-router` is deleted — verified absent; this is the only copy). Optionally also vendor a copy under `upb/docs/reference/panopticon-future/` | XS | `git ls-files future/` in panopticon returns 3 files; GitHub shows the commit |
| **P1 — Cost awareness** (G1+G11) | Port `model_info` pricing for all shared models into `routes.yaml` schema (add `pricing:` per model); extend `usage-logger.ts` to compute $ per entry; add $ totals to `GET /usage`; carry promo end-dates + markup notes into comments/WORKLOG | S | A known-cost call reproduces expected $ — e.g. one qwen3.6-flash request ≈ $0.004 as documented in HANDOFF:115; `curl /usage` shows per-model $ |
| **P2 — Provider cooldown** (G2) | Router keeps in-memory 429/5xx cooldown map per provider (default 5 min; configurable per provider — Zen needs hours); routing skips quarantined providers when alternates exist; `/health` + `upb status` expose state | S-M | Simulated 429 (mock upstream) causes route failover within one request and auto-recovery after TTL; unit test for the cooldown state machine (first tests in the repo — starts the test habit) |
| **P3 — Mistral Vibe** (G3) | Add per-provider `headers:` support to routes.yaml → router-config → adapter `extraHeaders`; add `mistral` provider (7 models + pricing from `config.yaml:79-159`); `MISTRAL_API_KEY` into `secrets.env` via `upb sync` | S-M | `upb run mistral/mistral-small` completes a round-trip through the Vibe plan (UA header present in provider-side acceptance); model appears in `/usage` with correct $ |
| **P4 — Benchmarks** (G4, optional) | `upb bench` over configured providers emitting or-bench-compatible JSON, or generalize `BenchmarkLoader`; feed rankings into `upb default` suggestions | M | A bench run over ≥3 providers yields a TPS/TTFB ranking consistent with observed `/usage` latencies |
| **P5 — Decommission panopticon** | See §7 | XS | §7 checklist |

Quick win order: P0 (minutes) → P1 (the only user-visible feature) → P2 (operational robustness) → P3 (recovers an idle subscription) → P4.

---

## 7. Panopticon disposition

**Recommendation: archive — commit `future/`, tag, stop the stack. Do not delete the repo.**

Before stopping anything, preserve (P0 + carried by P1/P3):
1. `future/` committed + pushed (untracked today — the only copy of `ai-model-router`'s code; its evolution story survives only in the Obsidian vault note `inference-stack/ai-model-router-to-panopticon.md`).
2. Pricing tables + Mistral Vibe wiring + promo/markup knowledge → lands in upb via P1/P3.
3. Nothing else holds unique state: Langfuse/LiteLLM DBs and Redis are verifiably empty; `cliproxy-auths/` is empty (no OAuth subscriptions ever added); `cliproxy-logs/main.log` (74KB) is trivial — copy if wanted.

Then:
- `docker compose down` (volumes contain nothing of value — re-verify the five zero-counts immediately before, in case something wrote to them since 2026-08-17). This reclaims ~6 containers incl. the Langfuse pair on a machine that also runs speakr/agent-stack.
- Secrets stay untouched in `~/.secrets.age` (`secrets` tool) — `MODELOS_AI_KEY`, `ALIBABA_TOKEN_PLAN_KEY`, `ZEN_API_KEY` are already consumed by upb's pipeline; `LANGFUSE_*_KEY` become dead entries, harmless.
- Update `~/.config/fabric/.env` (currently still pointing `LITELLM_API_BASE_URL=http://localhost:4000` — verified) to whatever fabric should use post-retirement, or accept fabric is decommissioned too.
- Repo: tag `v-final` (or `archive`) on `ebe6024`+P0-commit, push, set GitHub repo description to "Archived 2026-08 — superseded by upb". GitHub already holds an exact copy of `main` (verified via `ls-remote`).
- Update `hub/WORKSPACE_AUDIT.md:15` ("infrastructure you run daily") and upb `WORKLOG.md:25` (GitHub item is done) next time those files are touched.

---

## 8. Open questions

1. **Where did the Jul 20-21 Langfuse traces and spend rows go?** Documented as working (HANDOFF:111-116), now zero everywhere. Either `docker compose down -v` during the 2026-08-10 restart, or the volumes were recreated. Nothing forward-looking depends on the answer, but it determines whether "the observability plane silently lost its data" is a failure mode worth remembering.
2. **Is the Mistral Vibe subscription still active?** Wired on Jul 21 (`config.yaml:79-159`), zero usage data since (nothing transited :4000). P3 is pointless if the plan lapsed — check before building.
3. **Does anything besides fabric consume `localhost:4000`?** Fabric's `.env` points there but produced 0 requests in 96h. No other consumer was found on this Mac; the Linux box runs upb direct-to-provider (WORKLOG:67-73). If some unexamined script still targets :4000, decommissioning breaks it.
4. **Where does `SPEC-alibaba-cookie-usage.md` live?** Referenced by upb WORKLOG:27 but absent from the repo tree (only ARCHITECTURE/SETUP docs exist — verified). Presumably on the Linux box. It should be committed to upb before that box changes.
5. **`amalia-9b` — route it or drop it?** The only ULusofona model upb doesn't reach (G10). One line in `routes.yaml` if wanted.
6. **Should upb grow a test suite now?** P2 introduces the first stateful router logic (cooldown); both repos are at zero tests. A minimal `node --test` harness for `errors.ts`/cooldown/translate would be cheap insurance — flagged as a decision, not smuggled into scope.
7. **Zen free-tier policy** — panopticon config warns free models "may use data for training — no sensitive data" (`config.yaml:165`). upb routes Zen without recording any such policy (no equivalent note in `routes.yaml.example:64-83`). Confirm the trust-zone stance should be ported as documentation.
