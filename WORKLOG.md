# WORKLOG — upb multi-session coordination

> Shared work queue + session log for the **Universal Provider Bridge**.
> Any session (human or agent) can claim open work, log progress, and hand off.
> This file is the coordination hub — read it FIRST when joining, update it as you go.

## How to join (any session)

1. **Orient:** read this file, then `README.md` and `docs/SETUP.md`. For the live-system picture see the vault note `Universal Provider Bridge — Project Master Map`.
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

- [ ] **GitHub remote** — publish the repo. Needs `gh` installed + auth (`apt install gh && gh auth login`), then `gh repo create upb --public --source=. --push`. Currently local-only.
- [ ] **True fresh-box E2E** — run `install.sh` end-to-end on a virgin box/VM. Blocked here (no docker/podman/nspawn). Isolated boot-to-healthy is the best proof so far.
- [ ] **Alibaba cookie-based usage fetch** — implement per `SPEC-alibaba-cookie-usage.md` (Alibaba has NO API-key usage endpoint; console cookies required). Phase 1 = CLI script, Phase 2 = `upb usage` subcommand.
- [ ] **Reconcile live `~/bin/upb` with repo `cli/upb`** — repo is ahead (`sync --full`, `find_router_service`, discovery). Decide: deploy repo→live (set `UPB_ROUTER_ENV` to the live router env) or keep intentionally separate.
- [ ] **Confirm litellm `ornith-9b` → `bonsai-27b-1bit`** — gateway-side aliasing on `modelos.ai.ulusofona.pt` (see Open questions). Needs the LiteLLM admin / `model_list` check. Nothing to change in upb.
- [ ] **Adopt new zen free models** — `upb sync` discovery surfaced 5 new `-free` models (mimo-v2.5-free, ling-3.0-flash-free, nemotron-3-ultra-free, laguna-s-2.1-free, longcat-2.0-free). Add wanted ones under `providers.zen.models` in routes.yaml.
- [ ] **Add pricing for zai/deepseek/prime-intellect/ollama models** (no source data — needs provider price pages).

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
| 2026-08-17 | migration-from-panopticon | Implemented P1–P3 of `MIGRATION_FROM_PANOPTICON.md` §6: P1 per-model pricing in routes.yaml + `cost_usd` in the usage log and `/usage` totals; P2 provider cooldown/quarantine (`CooldownRegistry`, 429/retry-exhaustion marking, failover to an enabled `kind: upb` alternate serving the same model, fast-fail 503 otherwise, `/health` cooldowns, `upb status` display, zen 11h TTL) + first test suite in the repo (node:test, 14 tests incl. mock-upstream failover E2E); P3 per-provider `headers:` (auth-header-safe merge) + `mistral` Vibe provider (7 models, ports 8810–8816, pricing) + `MISTRAL_API_KEY` through secrets/sync. | `bade192`, `e84c047` |

---

## Open questions / findings

- **Model override bug (fixed 2026-08-07)** — Provider-level `claude_env.ANTHROPIC_MODEL` was silently overriding explicitly requested models. `upb run zai/glm-4.7` launched as `glm-5.2`. Root cause: `build_launch_env()` applied provider `claude_env` first, then only set route model if `ANTHROPIC_MODEL` wasn't already present. Fix: `explicit_model` flag forces route model to win when user specifies `provider/model`. Commit `6daa1fd`.
- **litellm `ornith-9b` serves `bonsai-27b-1bit`** (observed in LiteLLM monitoring, 2026-08-06). Verified NOT an upb bug: upb's :8901 proxy sends `ornith-9b` correctly; a direct gateway call with `model:"ornith-9b"` returns `model:"ornith-9b"`. Conclusion: the Lusófona gateway aliases `ornith-9b` → a deployment named `bonsai-27b-1bit` (server-side `model_list`). Gateway admin info endpoints are blocked for this key (`llm_api_routes` only). **Needs gateway-admin confirmation** whether that aliasing is intentional.
- **Alibaba token plan has a WEEKLY quota** (seen via 429: "1-week quota exhausted, resets <date>"), in addition to any per-5h window. No API-key usage endpoint exists.
- **`claude` binary fragility** — an npm reinstall can skip postinstall, leaving `claude.exe` as a stub → `OSError: Exec format error`. Fix: `node ~/.npm-global/lib/node_modules/@anthropic-ai/claude-code/install.cjs`.

---

## Key paths (quick reference)

| What | Where |
|---|---|
| Repo (source of truth) | `/home/fabio/projects/upb/` |
| Live router source | `~/shared-local/reports/claude-universal/` |
| Live CLI | `~/bin/upb` |
| Routes / secrets | `~/.config/upb/routes.yaml` · `~/.config/upb/secrets.env` |
| Live router env | `~/shared-local/reports/claude-universal/router-alibaba.env` |
| systemd unit | `~/.config/systemd/user/universal-router.service` |
| Usage log | `~/shared-local/reports/claude-universal/usage.jsonl` |
| Claude integration | `~/.claude/settings.json` (env block) |
