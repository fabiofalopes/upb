---
title: "Model list & picker — what to realize next"
written: 2026-11-05T21:33:00+01:00
written_iso: "2026-11-05T21:33+01:00"
author: hermes-agent
context: "13 days after the 2026-10-23 session; nothing was executed in between"
status: open
tags: [upb, model-registry, todo, human-in-the-loop]
---

# Model list & picker — what to realize next

**Written 2026-11-05 21:33 WET.** 13 days after the session that built the
registry and the health gate. Nothing was executed in between, and the
rot that caused is now measured, not theoretical.

> [!important] The headline
> **Your setup drifted while nobody was looking.** Pre-flight went from
> **15/15 working** to **2/15**. The cause is not exotic: the `commandcode`
> key stopped being accepted, and 8 auxiliary tasks + 4 of 5 fallback
> entries all pointed at it. Your *primary* survived because its OAuth token
> was refreshed on Oct 30.
>
> This is precisely the failure the health gate was built to catch. It caught
> it. It just had not been *scheduled*, so it caught it 13 days late and told
> nobody.

---

## Part 0 — Where things actually stand

### Verified working right now (2 of 15)

| What | Endpoint | Notes |
|---|---|---|
| **PRIMARY** | `openai-codex/gpt-6-luna` | works — token refreshed 2026-10-30, `codex_responses` dialect |
| **fallback:5** | `zai/glm-5.3-flash` | works |

### Verified broken

| What | Symptom | Bucket |
|---|---|---|
| `commandcode` (all models) | 401 — key rejected | provider-dead |
| 8 of 8 auxiliary tasks | all point at `commandcode` | provider-dead |
| fallback 1, 2, 3 | all point at `commandcode` | provider-dead |
| fallback 4 | `opencode-go` — no credential | no-key |
| LM Studio | not running (was running Oct 23) | unreachable |
| Lusófona gateway | `SSL: CERTIFICATE_VERIFY_FAILED` | error |
| `ollama-cloud` | 4 free models work, 7 plan-locked, **9 retired** | mixed |

**The Lusófona SSL failure is a local trust-store problem, not a server
problem.** The cert is GEANT-issued and valid to 2027-01-28; `curl` reports
`ssl_verify=20` (cannot get local issuer certificate). Python's bundled CA
set cannot verify the GEANT root. Fixable without touching the provider.

### Still true from October

- `upb` CLI **not deployed** — `~/bin/upb` is still the Aug 21 build
- upb router **not running** — nothing on 8705
- **10 commits unpushed** on `research/model-registry`
- `model_catalog.excluded_providers` is empty — the gate has never run
- No snapshots recorded, so no churn-rate metric exists yet

### What changed in the config while nobody was here

Someone (you, or another agent) migrated the Lusófona provider to the new
`providers:` block and changed the primary to `openai-codex/gpt-6-luna`. The
health gate's pinning **survived the migration** — the 14 working models are
still pinned with `discover_models: false`. That part held.

---

## Part 1 — Only you can do these

These need a decision, a purchase, a credential, or a judgement I cannot make
for you. Each one states the decision, the options, my recommendation, and
what happens if you do nothing.

### 1.1 — `commandcode`: dead key, or dead subscription?

> [!question] The decision
> Every `commandcode` model returns 401 "the key itself was rejected". That
> is an *authentication* failure, not a plan wall — so the credential is
> gone, not the tier. Two causes, and they need different fixes.

| Option | Action | Cost | Result |
|---|---|---|---|
| **A** | The subscription lapsed | none | key stops being accepted |
| **B** | The key rotated | none | new key needed |
| **C** | Account banned/flagged | none | needs a support ticket |

**My recommendation:** check whether you still have an active CommandCode
subscription. If yes → it's B, a rotated key; if no → it is A and the
question becomes whether to resubscribe.

**If you do nothing:** the auxiliary tasks stay dead. Every compression,
every title, every MCP tool call fails. Vision is down too.

> [!tip] Note
> 8 auxiliary tasks + 4 fallbacks pointed at **one** provider. That is the
> blast radius of a single provider being a single point of failure. Fixing
> the key restores all 12 at once — which is also why the fallback chain
> should not be one provider (see 1.4).

### 1.2 — The auxiliary tasks: one provider or several?

> [!question] The decision
> Right now all 8 auxiliary tasks use `commandcode`. If that provider dies
> again, everything auxiliary dies again.

| Option | Shape | Cost | Result |
|---|---|---|---|
| **A** | keep one provider | none | simple, but total blast radius |
| **B** | spread across providers | none | resilient |
| **C** | point aux at the primary provider | none | one less credential to manage |

**My recommendation: B**, specifically —
- `vision` → `ollama-cloud/gemma4:31b` (free, confirmed working, and it is
  *already* what the Oct 23 config used before it drifted)
- `compression`, `title_generation` → `openai-codex` (the primary — it is
  alive and refreshed)
- `web_extract`, `mcp`, `curator` → `zai/glm-5.3-flash` (confirmed working)

That way no single credential failure takes out more than a third of the
auxiliary surface, and **two of the three are already confirmed working
today** — no new subscription needed.

### 1.3 — Resume `alibaba`?

> [!question] The decision
> `alibaba` has a **valid** token but every model returns 403 "Access to
> model denied". That is a plan wall, not a broken key. You said you might
> resubscribe.

| Option | Action | Cost | Result |
|---|---|---|---|
| **A** | resubscribe | whatever it costs | 6 models unlock immediately |
| **B** | leave it | 0 | stays greyed; the gate keeps it out of the picker |
| **C** | remove it | 0 | 4 provider entries disappear from the pool |

**My recommendation: B for now, C if you are not resubscribing within a
month.** The gate already handles B correctly — the models stay visible as
greyed and do not appear in the picker. Leaving it costs nothing and keeps
the option open.

**Important:** when you do resubscribe, the next health-gate scan moves those
6 models back to selectable **with no config edit**. That was the whole point
of the bucket design.

### 1.4 — Should the fallback chain span providers?

> [!question] The decision
> The current chain is 4× `commandcode` + 1× `zai`. Four consecutive entries
> on one provider means the chain offers no protection against that provider
> failing — which is exactly what happened.

**My recommendation:** one entry per provider, ordered by preference:
`openai-codex` → `ollama-cloud` (free tier) → `zai`. **Three providers, one
model each.** Cheaper in tokens than a long single-provider chain and
actually resilient.

### 1.5 — Which provider do you want to be the default?

> [!question] The decision
> `openai-codex/gpt-6-luna` works and is a ChatGPT subscription — which
> means it burns *your plan allowance* rather than metered credits. Is that
> what you want as the default for everything?

| Option | Default | Cost profile |
|---|---|---|
| **A** | keep `openai-codex` | plan allowance, not per-token |
| **B** | `ollama-cloud/gemma4:31b` | free, but weaker at coding |
| **C** | `zai/glm-5.3-flash` | metered, but confirmed working |

**My recommendation: keep A for now**, because it is the only provider whose
credential was refreshed automatically. But if the ChatGPT plan is precious,
C is the honest metered choice and B is the free one.

### 1.6 — The Lusófona SSL certificate

> [!question] The decision
> The cert is valid (GEANT, to Jan 2027) but the local trust chain cannot
> verify it.

| Option | Action | Cost | Result |
|---|---|---|---|
| **A** | install the GEANT root in the system keychain | 1 min | Python + curl both trust it |
| **B** | set `ssl_verify: false` on that provider | 1 min | works, unverified TLS |
| **C** | leave it | 0 | provider stays unusable |

**My recommendation: A.** B disables certificate verification, which for a
remote endpoint is a real downgrade. A is the correct fix and it is one
command.

### 1.7 — LM Studio

> [!question] The decision
> LM Studio is not running. It was on Oct 23. Was that deliberate?

| Option | Action | Cost | Result |
|---|---|---|---|
| **A** | start it + load a model | RAM | free local inference returns |
| **B** | leave it off | 0 | no local fallback |

**My recommendation: A**, if only to have a *free* provider in the fallback
chain — it is the one thing that cannot be revoked, rate-limited, or
plan-gated. It also makes the whole setup survive a network outage.

---

## Part 2 — Ready to execute (say the word)

These are mechanical. I have the tools; each is a small, reversible change.

### 2.1 — Push the branch ⏱ 1 min

`research/model-registry` has **10 unpushed commits**, including the
registry subsystem, the health gate, and the docs. The remote was force-
pushed mid-session on Oct 23, so I held off. **Nothing is lost either way,
but the work is only on this machine.**

### 2.2 — Deploy the `upb` CLI ⏱ 1 min

`~/bin/upb` is still the Aug 21 build. The repo version has
`registry build/show/validate/slots/resolve/drift` and `snapshot`.

### 2.3 — Fix the pre-flight's blind spot ⏱ 30 min

Found today: the probe used a Chat Completions body for `openai-codex`,
which reports the *working* primary as broken. Fixed in
`tools/entitlement.py` (three dialects now) — but this is exactly the class
of bug the gate needs a test for. **I will add a dialect-matrix test.**

### 2.4 — Wire the gate to the new `providers:` block ⏱ 45 min

The gate was written for `custom_providers:`. The config has since migrated
to `providers:` — which Hermes converts to the same internal shape, so the
gate *should* already work. **Needs verification, not rewriting.**

### 2.5 — Schedule the scan ⏱ 15 min

The cron job from `docs/MODEL-LIST.md`:

```yaml
name: model-health-scan
schedule: "17 4 * * 1"     # Mondays 04:17
```

**This is the item that would have caught today's 13-day drift on day one.**
Without it, every future rotation repeats this exact discovery cost.

### 2.6 — Snapshot baseline ⏱ 5 min

`upb snapshot` has never been run on this machine. Without a baseline, rename
detection has nothing to diff against and the churn metric does not exist.

### 2.7 — Deploy the router ⏱ 2–3 h ⏱ **blocked**

The upb router is proven working on this Mac (verified live Oct 23: OpenAI
dialect → `ROUTER_OK`, Anthropic dialect → `ANTHROPIC_OK`, Hermes through it
→ `HERMES_OK`). Two blockers:

1. **No `routes.yaml` → `providers.yaml` converter.** The two formats
   differ; I hand-translated for the test. This is the real work.
2. **No launchd agent.** `scripts/install.sh` assumes Linux (systemd, apt).

Until this lands, `upb`'s `/usage` — the one metric source you own that ties
routing to cost — stays dark.

---

## Part 3 — The standing rule

> [!important] The one thing that matters
> **Nothing in this setup should be discovered by failing.** Every provider
> and model you rely on is probed on a schedule; the picker only offers what
> works; a retirement or an expiry is a notification, not a surprise.

Concretely, that means:

| Now | After |
|---|---|
| a dead model is found when you try it | a dead model is greyed in the picker |
| a dead provider is found when you try it | a dead provider is announced on Monday |
| you hand-maintain which models work | the gate maintains it |
| "which provider should I use" is a guess | "which provider should I use" is a number |

---

## Part 4 — Carried forward from the older backlog

These are from `WORKLOG.md` and `docs/ROADMAP.md` (August). They are still
open and none were touched in the Oct 23 session. Listed so nothing is
silently dropped, **not** because they are next.

| Item | Status | Note |
|---|---|---|
| **G0** — close the repo↔live gap | open | the blocker for 2.7 |
| **G1** — OpenCode provider collapse | open | gated on G0 + live upb health |
| **G2** — launcher split | design | see `docs/VISION.md` |
| **G3** — local-only spine | vision | |
| macOS deployment support | open | = item 2.7 |
| Alibaba cookie-based usage fetch | open | needs a spec file |
| Adopt new zen free models | open | 5 surfaced, never added |
| Pricing for zai/deepseek/prime-intellect/ollama | open | models.dev now covers most of this |
| Fresh-box E2E of `install.sh` | blocked | no docker/podman here |

**Two of these got easier since August.** "Add pricing" is largely solved by
models.dev (the registry already pulls it). "Adopt new zen free models" is
now automatic if the gate writes back to `routes.yaml` — which is a small
extension to what `--apply` already does.

---

## Part 5 — The order

```
  NOW (no decisions needed, ~5 min total)
    2.1 push branch          2.2 deploy CLI
    2.3 dialect test         2.6 snapshot baseline
    2.4 verify gate on providers: block
    2.5 schedule the scan      ← stops the bleeding

  THEN (needs you, ~15 min)
    1.2 spread the aux tasks   1.4 chain spans providers
    1.6 GEANT root cert        1.7 start LM Studio
    1.1 commandcode: which?

  LATER (bigger)
    2.7 deploy the router → /usage goes live
    registry fetcher (docs + catalogs + changelogs)
    LiteLLM per-key spend · ccusage + ClaudeBar for plan burn
```

**If you do exactly three things today:** 2.5 (schedule the scan), 1.2
(spread the aux tasks), 1.6 (fix the cert). Those three restore a working
system and stop the next drift from being invisible.

---

## Appendix — How to check any of this yourself

```console
$ python3 tools/preflight.py            # would a session start? 15 checks
$ python3 tools/providers.py            # which providers work, and why not
$ python3 tools/health_gate.py --scan   # the full provider/model matrix
$ python3 tools/entitlement.py          # per-model entitlement
$ python3 tools/health_gate.py --show   # the last scan's verdict
```

All live, all read-only unless you pass `--apply`.

---

*Next review: when the gate scan has run at least twice, or whenever
something breaks — whichever comes first.*
