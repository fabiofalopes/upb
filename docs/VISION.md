# upb — Vision & Territory

> What this project is *for*, and where it's moving. Not how it works (see
> `ARCHITECTURE.md`) — why it exists and what it's becoming.
>
> This document is deliberately about the **agentic** layer: the relationship
> between harnesses and providers, and where that relationship is heading.

## The one idea

**upb is the Universal Provider Interface (UPI) — the fleet's one stable
contract for talking to models.**

Every harness (OpenCode, Claude Code, Hermes, Pi, and whatever comes next)
carries the *same* provider-connectivity layer inside it: base URLs, auth,
model naming, protocol dialects. That layer is duplicated across every tool.
upb externalizes it into a single service, and every harness points at it.

The result: a harness's provider becomes a config choice behind one endpoint,
not a rewrite. You move fast — swap models, A/B providers, fall back to a free
tier — by editing one YAML file.

## The two-layer model: spine and appliance

```
  Harnesses (the appliances)          ── each has its own brain
  OpenCode · Claude Code · Hermes · Pi     runtime, skills, memory, planning
           │  all point at the same spine
           ▼
  ┌────────────────────────────────────────┐
  │  upb  —  the Universal Provider I/F    │  ← one shared service
  └────────────────────────────────────────┘     (keys, routing, retries, usage)
           │  routes by provider/model prefix
           ▼
  Providers  alibaba · zai · deepseek · litellm · zen · ollama · …
```

- **The appliance** is the harness: context management, the tool-calling loop,
  skills, memory, planning, delegation. This is where the "agent" lives.
- **The spine** is upb: protocol translation, routing, key management, retries,
  usage logging. This is where "provider access" lives.

upb is **not a component packed inside each harness**. It is a shared wall
socket. You don't build a socket into every toaster; you put one socket on the
wall and plug everything into it.

The separation is the whole trick:

- **Keep the spine dumb and stable.** Its value is thinness — two dialects,
  routing, keys, retries, usage. The moment it absorbs harness concerns
  (session state, memory, skill routing, orchestration) it stops being
  universal and becomes a monolith every harness must conform to.
- **Keep the brains in the appliances.** Fleet-level *transport* concerns
  (keys, usage, rate-limit pooling, a single audit trail) belong in the spine;
  everything agentic belongs in the harnesses.

## Why it feels like one object

The seam between harness and spine is invisible because both sides speak the
same vocabulary: `provider/model` ids (`litellm/amalia-9b`,
`opencode-go/deepseek-v4-pro`). OpenCode lists `litellm/*`; upb routes
`litellm/*`. The two systems are already co-designed — `upb sync` even pulls
keys out of OpenCode's auth store.

That shared vocabulary is what makes the fleet feel like a single object. But
it is still two layers, and keeping them separate is what preserves the
"universal" property.

## Claude Code: the anchor and the hostile client

Claude Code is the primary client — and the hard one.

- It **only speaks the Anthropic Messages API** and expects `claude-*` model
  names. It cannot talk to an OpenAI-compatible endpoint directly.
- It **ships new builds weekly**, and each build can break the translation
  layer (new API surface, streaming shapes, tool-call formats). Every week is a
  maintenance gamble on whether the next build still works.
- It is **hostile by default**: prompt injection, phoning remote servers,
  eating disk. upb doubles as the containment point — a local, watched, capped
  boundary that Claude Code sits behind.

The other harnesses (OpenCode, Hermes) are easy — they speak OpenAI natively
and welcome the proxy. Claude Code is the one that costs a weekly "saga" to
keep alive, and the one that most needs the private, local spine.

## The launcher entanglement

`upb run` grew from a route-control command into a **Claude Code launcher**:
it spawns a proxy pinned to a provider/model and launches `claude` through it.
That launcher is how most Claude Code work actually happens today.

This is a deliberate, somewhat odd design — a launcher embedded in a universal
proxy bridge. It's also genuinely good: `upb run` is a clean way to drive
Claude Code through the gateway.

The tension: the harness is increasingly **attached to the launcher**. The
`upb` side has absorbed a chunk of Claude Code's harness. The resolution is a
**split with a thin seam**, not a deletion:

- **Keep the bridge as the bridge** — transport, keys, routing, usage.
- **Extract the "breaking Claude Code" concern** into its own workspace: the
  community-driven work of patching each new Claude Code build, tracking
  prompt-injection defenses, and keeping the translation layer current.

The launcher stays embedded in the gateway (it's useful), but the *breaking*
work — the part that changes every week — deserves its own home so it doesn't
drag the stable spine through every Claude Code release cycle.

## The territory we're moving toward

upb's trajectory, beyond being a router:

1. **A liaison for backends** — it connects *other* backends (LiteLLM, Ollama,
   Z.AI, Alibaba, PrimeIntellect), but mostly it connects *our own*. It is
   becoming the gateway to our own model infrastructure, not just a pass-through
   to third parties.
2. **Monitoring** — `usage.jsonl` and the `/usage` endpoint already record
   every request. The payoff is one place watching every harness's token burn,
   across every provider. This is the single best feature of the project:
   *knowing* how different harnesses are actually running and spending.
3. **A "light LLM" from the ground up** — the spine is evolving toward its own
   model-serving layer, grown deliberately and incrementally. It is single-user
   today; multi-user is a design target, not an afterthought.

## The local-only spine

The destination: **one upb on a box with only local models behind it.**

`routes.yaml` declares only `litellm` (amalia-9b, omnicoder-9b, ornith-9b,
qwen3.5-9b-mtp). Cloud providers are dropped — not blocked, but *absent*, so
cloud commands simply have nothing to resolve to. Every harness on that box
points at the spine.

This is the containment payoff and the small-model payoff in one deployment:
Claude Code can't phone remote servers because the vocabulary has no remote
entries.

## The small-model harness thesis

The reason local-only is viable, not just private:

Small models are distilled-down but still hold real power. They fail when given
unstructured, open-ended work; they succeed when given **structure, skills, and
many attempts**. The harness — the agent structure, the skills, the
orchestration, the "throw them at problems and give them lots of attempts"
loop — is exactly what compensates for the smaller models.

Give a small model a consistent task and a clean script to call, and it runs it
perfectly. The harness's job is to make the task easy enough that the small
model can put 2+2 together. Structure is the multiplier; the distilled power is
the raw material.

That's the exchange: trade raw model power for harness structure, and you get a
private, local, deterministic agent fleet that costs nothing to run.

## The operating principle

This is not a set-and-forget project. There are decision gates, ideas on the
table, and specific moments in time where a choice has to get made. The cost of
operating here is **understanding what we're doing at all times** — every
detail, before and during.

The alternative — acting with a lot of agency on a thing you don't understand —
is not a healthy relationship with the work. The tight leash is deliberate,
especially where the harness threatens to grow too much around the upb side.

## The community context

The "breaking Claude Code" thread connects this project to a community doing
the same at scale: reverse-engineering and patching Claude Code to work with
alternative providers. upb is built on analyzing what that community already
discovered. It is both a tool and a way of joining that work — not just
maintaining one install, but participating in the pattern.

---

*See `ROADMAP.md` for the decision gates, lanes, and open questions that turn
this vision into tasks. See `ARCHITECTURE.md` for how the router actually
works. See `WORKLOG.md` for the live backlog.*
