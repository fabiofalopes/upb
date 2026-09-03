# upb — Roadmap, Decision Gates & Open Questions

> The strategic layer. `VISION.md` says *what/why*; this says *what next, and
> what has to get decided first*. The tactical backlog (claimable work items)
> lives in `WORKLOG.md`; this file holds the gates and lanes that order it.

## Decision gates

A gate is a point where a choice must be made before dependent work can start.
Each has a trigger and a decision.

| Gate | Trigger | Decision to make | Blocks |
|------|---------|------------------|--------|
| **G0 — repo↔live gap** | Now | Deploy repo → live, or keep the two intentionally separate? The live proxy runs from `~/shared-local/reports/claude-universal/`, not this repo. Editing the repo does not change the running Claude Code until deployed. | *everything* — a fix that doesn't reach the live system is theoretical |
| **G1 — provider collapse** | After G0; live upb proven healthy | Collapse OpenCode to a single `upb` provider (remove `alibaba-token-plan`, `opencode`, `opencode-go`, `litellm` from the auth store + json; remap `model` → `upb/…`; update `AGENTS.md` model policy). Only when live upb routes alibaba + litellm correctly. | monitoring payoff; single-spine topology |
| **G2 — launcher split** | When the weekly Claude Code "saga" starts dragging the spine | Extract the "breaking Claude Code" concern into its own workspace, keep `upb run` embedded as a thin launcher. | clean separation of stable spine vs churning patch work |
| **G3 — local-only spine** | When local models prove viable | Deploy one upb with only `litellm` models, cloud dropped. | the small-model harness experiment; full containment |
| **G4 — multi-user** | First second user appears | Design the "light LLM" layer for multiple users instead of one. | the spine's evolution from personal gateway to shared infra |

## Lanes (priority order)

Workstreams, each gated as above.

- **Lane A — Close the repo↔live gap (G0).** Map exactly what differs between
  this repo and the live `~/shared-local/reports/claude-universal/` +
  `~/bin/upb`, then get repo→live deploy working. This turns the weekly saga
  from "hand-edit live files" into "patch repo, deploy, done."
- **Lane B — OpenCode provider collapse (G1).** OpenCode becomes a pure client
  of the spine. Steps: verify live upb health → add single `upb` provider →
  remap `model` → remove redundant auth providers → update model policy. The
  single-monitoring-point payoff lands here.
- **Lane C — Claude Code compatibility + containment.** A repeatable routine:
  on each new build, exercise the fragile points (messages, streaming, tool-call
  reassembly, `count_tokens`), catch breakage, patch `translate.ts`/`stream.ts`.
  Plus confirm the local trust boundary holds against prompt-injection and
  remote-chatter behavior.
- **Lane D — Launcher split (G2).** The "breaking Claude Code" workspace,
  holding the community-driven patch work, decoupled from the stable spine.
- **Lane E — Local-only spine (G3).** The thin deployment: one upb, only
  `litellm`, cloud absent.
- **Lane F — UPI formalization.** Codify the spine/appliance contract: what the
  spine owns (keys, usage, retries, audit) vs what stays in the harnesses
  (skills, memory, planning). Mostly a contract/decision, little code. This is
  where the "one object" intuition gets written down without letting upb bloat.

## Open questions

Concrete unresolved items (also tracked in `WORKLOG.md`):

- **litellm `ornith-9b` → `bonsai-27b-1bit`** — the Lusófona gateway aliases
  `ornith-9b` to a deployment named `bonsai-27b-1bit`. Verified NOT an upb bug;
  needs gateway-admin confirmation whether the alias is intentional.
- **Alibaba weekly quota** — the token plan has a weekly quota (429 observed),
  on top of the per-5h window. No API-key usage endpoint exists; usage fetch
  requires console cookies (see `SPEC-alibaba-cookie-usage.md`).
- **`claude` binary fragility** — an npm reinstall can skip postinstall,
  leaving `claude.exe` as a stub → `Exec format error`. Fix is manual
  (`node …/install.cjs`).
- **repo↔live reconciliation** — repo `cli/upb` is ahead of live `~/bin/upb`
  (`sync --full`, `find_router_service`, discovery). Decide direction (G0).
- **OpenCode model policy follows the remap?** — `AGENTS.md` pins
  `alibaba-token-plan/qwen3.8-max-preview` as the only allowed model. When the
  provider collapse happens, does the "only model" rule follow the `upb/…`
  path, and who owns that policy?
- **zen free-model adoption** — `upb sync` surfaced new `-free` models
  (mimo-v2.5-free, ling-3.0-flash-free, nemotron-3-ultra-free, etc.). Which are
  wanted in `providers.zen.models`?

## Moments in time (triggers)

Recurring/event-driven points where work comes up, so nothing is "set and
forget":

- **Every new Claude Code build** → run the compatibility routine (Lane C).
- **When live upb proves healthy** → provider collapse (G1) unlocks.
- **When a second harness needs monitoring** → extend the usage/monitoring
  layer to it (the single-spine payoff grows).
- **When local models prove viable in a sandbox** → local-only deployment (G3).
- **When a second user appears** → multi-user design (G4).
- **When the repo diverges from live again** → re-check the G0 decision.

## Operating note

None of this is fire-and-forget. The project moves through deliberate
decision gates, not a straight line. Each gate is cheap to *document* now and
expensive to *reverse* later — so the pattern is: write the decision down,
then act when its trigger fires.

---

*Live backlog: `WORKLOG.md`. Design details: `ARCHITECTURE.md`. Framing:
`VISION.md`.*
