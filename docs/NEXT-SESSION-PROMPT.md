# NEXT SESSION PROMPT — copy this into a fresh session

Everything below is a **prompt to give the next Hermes session**. It is
self-contained: the next agent does not need any of this conversation.

---

## Paste this:

```
Read ~/projetos/hub/upb/docs/HANDOFF-2026-11-05.md first — it is the brief
for this session and it is verified against the live system.

Then read docs/todo/2026-11-05T21-33+0100-model-list-and-picker.md, which
holds the decisions that are mine (the human's) to make.

Context you need before starting:

I am fabiofalopes. We spent 2026-10-23 building a canonical model registry
and a "health gate" for the upb project (~/projetos/hub/upb). The idea:
provider model ids churn constantly, so a config that names models directly
is wrong before you finish reading it. The gate probes every provider/model
pair with a real 1-token call and sorts them into selectable / greyed /
retired / busy / removed / provider-dead, then writes that back into the
Hermes config so /model only offers what actually works.

13 days passed with nothing executed. When we came back, pre-flight had gone
from 15/15 working to 2/15. The gate had caught it but nobody had been
told. Three findings from that gap are already fixed (wrong wire dialect for
openai-codex, a missing HARICA root cert, and the gate not reading the new
providers: config block).

There is one decision I need from you at the start: the `commandcode` key
now returns 401 on every model, and 8 of my auxiliary tasks plus 3 of 5
fallback entries point at it. Tell me what to do with those — spread them
across the providers that are verified working today (openai-codex,
zai/glm-5.3-flash, ollama-cloud's free models), or something else you
prefer. Ask me if you need to know more first.

After that, in priority order:
1. Commit and push the 11 unpushed commits on branch research/model-registry
   (read the handoff §0 first — the remote was force-pushed in October, so
   check before you push).
2. Implement the biggest missing feature: the health gate can grey models
   out but cannot DISCOVER new upstream models. That is why the Lusofona
   gateway's catalogue rotation (it now serves lfm2-*/lfm3-* instead of the
   amalia-9b/ornith-9b family I had declared) left me with an empty
   provider instead of a one-line suggestion.
3. Schedule the scan as a cron job, so this class of drift is a
   notification and not a discovery.

Work in the repo, commit in small messages, and tell me what you changed
and what you verified. Do not push anything to main.
```

---

## Why this prompt is shaped this way

**It leads with the brief, not the task.** The next session needs the handoff
before it needs instructions — otherwise it re-derives what the handoff
already states.

**It states the context compactly.** The registry/gate design is described in
one paragraph with the *why* (ids churn) rather than a feature list, so the
next agent understands the intent and can extend it rather than just
following steps.

**It asks for the one blocking decision first.** The `commandcode` question
is genuinely the user's — it needs their subscription status — and everything
downstream (spreading aux tasks, the fallback chain) depends on it. Asking
it up front prevents a session from optimising around a provider that may
not come back.

**It names the top three tasks with their rationale.** The gate-discovery
feature is listed second because it is what turns "the provider is gone"
into "add `lfm3-1.7b`" — the difference between a diagnosis and a decision.
The cron job is third because it is what stops the next 13-day gap from
repeating.

**It sets the working norms.** Commit small, verify, report, don't push to
main.

**It avoids over-specifying.** The handoff has the details; the prompt
points at them rather than duplicating them, so there is one source of truth
that can be corrected in one place.

---

## If you want a shorter version (for a quick start)

```
Read ~/projetos/hub/upb/docs/HANDOFF-2026-11-05.md and follow it. Start with
§0 (commit + push), then ask me about the commandcode key (401 on everything,
and 8 aux tasks + 3 fallbacks point at it). Then do §4.1 — teach the health
gate to discover new upstream models — and §7, schedule the scan.
```

---

## Notes for the human

- **The handoff is a repo file, not a message.** It survives; the prompt
  above just points at it. If you start a session on a different machine,
  the branch has to be pushed first — which is item 1 in §0.
- **The dated todo still stands** (`docs/todo/2026-11-05T21-33+0100-*.md`).
  One line in it is now superseded: it says the Lusófona provider has 14
  working models. It has **zero** — the gateway rotated its catalogue. The
  handoff §1 has the current numbers.
- **The handoff is honest about gaps.** §4 lists what the tooling still
  cannot do, so the next session doesn't mistake a working tool for a
  complete one.
