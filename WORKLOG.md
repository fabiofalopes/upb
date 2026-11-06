# WORKLOG — upb multi-session coordination

> Shared work queue + session log for the **Universal Provider Bridge**.
> Any session (human or agent) can claim open work, log progress, and hand off.
> This file is the coordination hub — read it FIRST when joining, update it as you go.

## How to join (any session)

1. **Orient:** read this file, then `README.md`, `docs/SETUP.md`, and the strategy layer — `docs/VISION.md` (framing/territory) and `docs/ROADMAP.md` (decision gates, lanes, open questions). For the live-system picture see the vault note `Universal Provider Bridge — Project Master Map`.
2. **Check "In progress"** — do not duplicate claimed work. If something is stale (claimed long ago, no commits), it may be reclaimable; note the takeover in the session log.
3. **Pick an "Open" item** (or add a new one). Move it to "In progress" with your session id + date.
4. **Work in small, well-messaged commits.** Keep the repo secret-free (never commit keys or personal paths).
5. **Log it** in the Session log table, then move the item to "Done" (with the commit hash).

### Ground rules
- **Secrets never enter the repo.** Keys live in `~/.config/upb/secrets.env` (chmod 600), managed by `upb sync`.
- **Don't break the live system** when testing installer/sync changes — use `--dry-run` and isolated `--prefix`/env overrides.
- **Repo vs live:** the repo is the source of truth; the live setup still runs from `~/shared-local/reports/claude-universal/`. Editing the repo does NOT change the live proxy until deployed.
- **Verify before marking Done** — build passes, no secrets, behavior tested.

---

## Open (unclaimed)

- [x] **GitHub remote** — done: repo published at https://github.com/fabiofalopes/upb (pushes since 2026-08-17).
- [ ] **True fresh-box E2E** — run `install.sh` end-to-end on a virgin box/VM. Blocked here (no docker/podman/nspawn). Isolated boot-to-healthy is the best proof so far.
- [ ] **Alibaba cookie-based usage fetch** — implement per `SPEC-alibaba-cookie-usage.md` (Alibaba has NO API-key usage endpoint; console cookies required). Phase 1 = CLI script, Phase 2 = `upb usage` subcommand.
- [ ] **Reconcile live `~/bin/upb` with repo `cli/upb`** — repo is ahead (`sync --full`, `find_router_service`, discovery). Decide: deploy repo→live (set `UPB_ROUTER_ENV` to the live router env) or keep intentionally separate.
- [ ] **Confirm litellm `ornith-9b` → `bonsai-27b-1bit`** — gateway-side aliasing on `modelos.ai.ulusofona.pt` (see Open questions). Needs the LiteLLM admin / `model_list` check. Nothing to change in upb.
- [x] **Adopt new zen free models** — resolved by the catalog invariant (2026-10-05): zen's live `/models` IS the list; every surfaced `-free` model is immediately runnable (`upb run zen/<id>`) with zero config. `discover_match: free` only filters the display.
- [ ] **Add pricing for zai/deepseek/prime-intellect/ollama models** (no source data — needs provider price pages).
- [ ] **macOS deployment support** — installer currently assumes Linux (systemd unit + apt dep bootstrap). For a local Mac instance: `--skip-deps --no-systemd --no-claude` works (Node 22 + PyYAML present), but needs a launchd user-agent template for the persistent router + Mac-native notes in SETUP.md. Fabric on the Mac is pre-pointed at `http://127.0.0.1:8705/v1` and waiting on this.
- [ ] **Close the repo↔live gap (G0)** — map exactly what differs between this repo and the live `~/shared-local/reports/claude-universal/` + `~/bin/upb`, then get repo→live deploy working. Prerequisite for everything below. See `docs/ROADMAP.md`.
- [ ] **OpenCode provider collapse (G1)** — `[GATED on G0 + live upb health]` collapse OpenCode to a single `upb` provider: verify live upb routes alibaba+litellm → add `upb` provider in `opencode.json` → remap `model` → remove redundant providers from auth store → update `AGENTS.md` model policy. See `docs/ROADMAP.md`.
- [ ] **Launcher split (G2)** — `[design]` extract the "breaking Claude Code" concern into its own workspace; keep `upb run` embedded as a thin launcher. See `docs/VISION.md` § "The launcher entanglement".
- [ ] **Local-only spine (G3)** — `[vision]` deploy one upb with only `litellm` models, cloud dropped. See `docs/VISION.md` § "The local-only spine".

## In progress

_(none — claim from Open above)_

## Done

- **2026-08-06** — Initial release: monorepo (router + cli + config + docs + scripts). `4969aa5`
- **2026-08-06** — Self-reproducing installer (`install.sh`/`uninstall.sh`, Claude Code takeover, `upb sync` router.env generation, service-name detection). `d7e07b6`
- **2026-08-06** — New-model discovery in `upb sync` (`discover: true` + `discover_match`). `4736b3d`
- **2026-08-07** — Fix: explicit model request (`upb run provider/model`) now overrides provider `claude_env.ANTHROPIC_MODEL`. `6daa1fd`

---

## Session log

| Date | Session | What was done | Commits |
|---|---|---|---|
| 2026-08-06 | orchestrator + fix-2 | Repo creation, installer, docs, service-name fix, model discovery; live key restructure + usage logging + bare-claude routing; litellm/bonsai diagnosis | `4969aa5`, `d7e07b6`, `4736b3d` |
| 2026-08-07 | orchestrator | Fixed model override bug: `upb run provider/model` now correctly overrides provider-level `claude_env.ANTHROPIC_MODEL` when a specific model is explicitly requested. Previously `zai/glm-4.7` always launched as `glm-5.2`. | `6daa1fd` |
| 2026-08-13 | orchestrator | Wrote strategy layer: `docs/VISION.md` (spine/appliance framing, fleet, launcher entanglement, territory, local-only + small-model thesis) and `docs/ROADMAP.md` (decision gates G0–G4, lanes A–F, open questions, trigger moments). No code. | — |
| 2026-08-17 | migration-from-panopticon | Implemented P1–P3 of `MIGRATION_FROM_PANOPTICON.md` §6: P1 per-model pricing in routes.yaml + `cost_usd` in the usage log and `/usage` totals; P2 provider cooldown/quarantine (`CooldownRegistry`, 429/retry-exhaustion marking, failover to an enabled `kind: upb` alternate serving the same model, fast-fail 503 otherwise, `/health` cooldowns, `upb status` display, zen 11h TTL) + first test suite in the repo (node:test, 14 tests incl. mock-upstream failover E2E); P3 per-provider `headers:` (auth-header-safe merge) + `mistral` Vibe provider (7 models, ports 8810–8816, pricing) + `MISTRAL_API_KEY` through secrets/sync; upb verify catalog-audit command (listing diff + opt-in 1-token probe) | `bade192`, `e84c047` |
| 2026-10-05 | macs consolidation | Mac-lane fanout end-to-end: router `model_map` lane aliases (bare `lane` ids in `/v1/models` + upstream-id mapping), undici `headersTimeout` fix (long non-streaming generations 502'd at 300s while lanes finished the work), live-catalog `default_model` gating, hot-swap 60s catalog TTL, `upb models` collapsed lane view (`lane → loaded model`; catalog cache now stores full entries), `scripts/sync-macs.py` (live catalogs → macs-providers.yaml + pi models.json), `scripts/check-drift.sh` (G0 guard: symlink + proxy.dir + old copy gone). Strategy: G0 marked resolved, 2026-10 consolidation checkpoint + near-future spec in `docs/ROADMAP.md`. Stable remote push for larger-scale testing. NOTE 2026-10-05: the fleet generator that lived at `scripts/sync-macs.py` was removed and purged from history — Mac/fleet topology belongs to the private `mac-inference` repo (`control/render.py`). | see `git log` |
| 2026-10-27 | orchestrator | Follow-up: dynamic proxy (port 9025, mac-256/glm53flash) crashed on upstream stream timeout — unhandled 'error' event on Readable took down the process. Hardened router: added error listeners on transformer/keepalive/res in both streaming paths, keepalive close→clearInterval, and process-level uncaughtException/unhandledRejection safety net (src/index.ts, src/utils/stream.ts); rebuilt dist. Restarted universal-router + upb-macs-router to load new code; killed 11 stale dynamic proxies. Health green again. | — |
| 2026-10-27 | orchestrator | Fixed UNHEALTHY claude-health gate blocking `upb run zai/glm-5.3-flash`: remapped retired `ornith-9b`/`amalia-9b` → `ornith-35b`/`minicpm-v47` in `~/.config/upb/router.env` (upstream modelos.ai dropped the 9b variants) and restarted universal-router.service; corrected stale `~/bin/claude-health` paths (DIST→~/projects/upb/router/dist, ROUTER_ENV→~/.config/upb/router.env); removed unused `claude-zen-nemotron` launcher; excluded `claude-health` from doctor hygiene glob. Verified: claude-health HEALTHY (exit 0), upb doctor exit 0, smoke PONG clean. | — |
| 2026-10-05 | catalog invariant | **Live `/models` is the single source of model truth, enforced in code.** CLI: `catalog: live` is the DEFAULT (opt-out is deprecated `catalog: static`); `upb run`/`upb default` validate against a LIVE /models fetch each time (stale cache only as unreachable fallback); remote TTL cut 3600→300s; wire pins derive from the route model with role keys (`opus_model`/`sonnet_model`/`haiku_model`); `upb verify` audits every pin against the live catalog (stale pin = exit 3) and `upb run` refuses to launch with one; `models:` is now pricing metadata only (`UPB_PRICING` → cost_usd on dynamic routes). Router: proxy `GET /v1/models` mirrors the upstream catalog (`utils/upstream-catalog.ts`, stale-while-error, `UPB_CATALOG_TTL`/`UPB_MODELS_URL`; tailnet-local ttl=0 reflects lane swaps instantly). Tests: +2 catalog-passthrough E2E (mirror + retirement, stale-while-error); 16/16. Examples/README/ARCHITECTURE/ROADMAP document the invariant; zen-adoption items closed. | — |

---

## Open questions / findings

- **Model override bug (fixed 2026-08-07)** — Provider-level `claude_env.ANTHROPIC_MODEL` was silently overriding explicitly requested models. `upb run zai/glm-4.7` launched as `glm-5.2`. Root cause: `build_launch_env()` applied provider `claude_env` first, then only set route model if `ANTHROPIC_MODEL` wasn't already present. Fix: `explicit_model` flag forces route model to win when user specifies `provider/model`. Commit `6daa1fd`.
- **litellm `ornith-9b` serves `bonsai-27b-1bit`** (observed in LiteLLM monitoring, 2026-08-06). Verified NOT an upb bug: upb's :8901 proxy sends `ornith-9b` correctly; a direct gateway call with `model:"ornith-9b"` returns `model:"ornith-9b"`. Conclusion: the Lusófona gateway aliases `ornith-9b` → a deployment named `bonsai-27b-1bit` (server-side `model_list`). Gateway admin info endpoints are blocked for this key (`llm_api_routes` only). **Needs gateway-admin confirmation** whether that aliasing is intentional.
- **Alibaba token plan has a WEEKLY quota** (seen via 429: "1-week quota exhausted, resets <date>"), in addition to any per-5h window. No API-key usage endpoint exists.
- **`claude` binary fragility** — an npm reinstall can skip postinstall, leaving `claude.exe` as a stub → `OSError: Exec format error`. Fix: `node ~/.npm-global/lib/node_modules/@anthropic-ai/claude-code/install.cjs`.
- **OpenCode model policy vs provider collapse** — `AGENTS.md` pins `alibaba-token-plan/qwen3.8-max-preview` as the only allowed model. When OpenCode collapses to a single `upb` provider (G1), does the "only model" rule follow the `upb/…` path, and who owns that policy? Open (2026-08-13).

---

## Key paths (quick reference)

| What | Where |
|---|---|
| Repo (source of truth) | `~/projects/upb/` |
| Live router source | `~/shared-local/reports/claude-universal/` |
| Live CLI | `~/bin/upb` |
| Routes / secrets | `~/.config/upb/routes.yaml` · `~/.config/upb/secrets.env` |
| Live router env | `~/.config/upb/router.env` (universal-router.service; was router-alibaba.env, retired) |
| systemd unit | `~/.config/systemd/user/universal-router.service` |
| Usage log | `~/shared-local/reports/claude-universal/usage.jsonl` |
| Claude integration | `~/.claude/settings.json` (env block) |
