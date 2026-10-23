# upb on this machine — what is proven, what is not

**Verified 2026-10-23 by booting the router and making real calls.** This
document records exactly what was tested and what was found, because the
answer is not a simple yes or no.

## Short answer

**The upb router works on this Mac and Hermes can route through it — proven
with live API calls. But the `upb` CLI is NOT deployed, the router is NOT
running as a service, and Hermes is NOT configured to use upb by default.**

Three separate things, three different states. Conflating them is what makes
the status confusing.

## What was tested, and the results

### 1. The router boots and serves — PROVEN

```
$ cd router && UPB_CONFIG=<providers.yaml> LOCAL_SECRET=<secret> node dist/index.js
```

```
$ curl http://127.0.0.1:8799/health
{"status":"ok","service":"universal-provider-router","version":"1",
 "providers":["alibaba","zai","zen","mistral","litellm","prime-intellect",
              "pi-own","deepseek","ollama-cloud"],
 "active_provider":"ollama-cloud","cooldowns":{},"uptime":7.49}
```

### 2. Live inference through the router — PROVEN

OpenAI dialect:

```
$ curl -X POST http://127.0.0.1:8799/v1/chat/completions \
    -H "Authorization: Bearer <local_secret>" \
    -d '{"model":"ollama-cloud/gemma4:31b", ...}'

{"id":"chatcmpl-752","model":"gemma4:31b","system_fingerprint":"fp_ollama",
 "choices":[{"message":{"role":"assistant","content":"ROUTER_OK"},"finish_reason":"stop"}],
 "usage":{"prompt_tokens":21,"completion_tokens":5,"total_tokens":26}}
```

Anthropic dialect (what Claude Code speaks) — same router, translated:

```
$ curl -X POST http://127.0.0.1:8799/v1/messages \
    -H "x-api-key: <local_secret>" -H "anthropic-version: 2023-06-01" \
    -d '{"model":"ollama-cloud/gemma4:31b", ...}'

{"id":"msg_chatcmpl-237","type":"message","role":"assistant",
 "content":[{"type":"text","text":"ANTHROPIC_OK"}],
 "usage":{"input_tokens":23,"output_tokens":6}}
```

### 3. Hermes → upb router → provider — PROVEN

A scratch `HERMES_HOME` (real config untouched) with the router as a custom
provider:

```yaml
custom_providers:
  - name: upb-router
    base_url: http://127.0.0.1:8799/v1
    api_key: <local_secret>
    model: ollama-cloud/gemma4:31b
```

```
$ HERMES_HOME=<scratch> hermes -z "reply with exactly: HERMES_OK" \
    --provider custom:upb-router -m "ollama-cloud/gemma4:31b"

HERMES_OK
```

And the router's own accounting confirms the traffic went through it:

```json
{ "total_requests": 4, "total_tokens": 13204,
  "by_provider": { "ollama-cloud": { "requests": 4, "completion_tokens": 32 } },
  "by_model":    { "gemma4:31b":  { "requests": 4 } } }
```

## Three things that are NOT done

| Thing | State | Evidence |
|---|---|---|
| `upb` CLI (the new one with `registry`/`snapshot`) | **not deployed** | `~/bin/upb` has no `cmd_registry`; still the Aug 21 build |
| upb router as a running service | **not running** | nothing listening on 8705; the test router on 8799 was stopped after the test |
| Hermes defaulting to upb | **not configured** | real `config.yaml` has no `upb-router` provider and no `8799`/`8705` reference |

So: **the plumbing works, nothing is switched over.** Running Claude Code or
Hermes today goes direct to providers, not through upb.

## Findings from the test — things that will bite

### The router's config format differs from `routes.yaml`

The router reads `providers.yaml` (or `UPB_CONFIG`), with this shape:

```yaml
providers:
  ollama-cloud:
    type: openai_compatible
    base_url: https://ollama.com/v1
    api_key: <value>        # a VALUE, not a reference
    timeout: 300000
    kind: upb
    enabled: true
```

`routes.yaml` uses a different shape — `key: {type: env, var: X}` references,
per-model `pricing`, `port`, `claude_env`. **There is no converter.** The
config was hand-translated for this test. That translation is a missing piece
if upb is to run on this Mac, and it is where a `upb router-env` subcommand
would belong.

### `LOCAL_SECRET` env beats the config value

`router/src/index.ts:33`:

```ts
const LOCAL_SECRET = process.env.LOCAL_SECRET || routerCfg.defaults.local_secret;
```

`defaults.local_secret` in `providers.yaml` is **only a fallback**. With
`LOCAL_SECRET` unset, `/v1/messages` rejects the config's own secret with
`Invalid local key`. Any launcher that sets `LOCAL_SECRET` must agree with the
config, or the Anthropic path breaks while the OpenAI path works — exactly the
split seen during testing.

### Three providers have placeholder keys

`~/.config/upb/secrets.env`:

| Provider | Key state |
|---|---|
| `mistral` | **`'your-key-here'`** — a literal placeholder |
| `deepseek` | missing (provider is `enabled: false` — consistent) |
| `pi-own` | none needed (local, `key: none`) |

`mistral` failing with `401 Invalid API Key` is the placeholder, not a broken
integration. The provider is enabled in `routes.yaml` with a full model list
and pricing, so it looks configured while being inert.

### `upb sync` does not generate `router.env`

`cmd_sync` only *pushes* `ALIBABA_TOKEN_PLAN_KEY` into an **existing**
`router.env`. It never creates one. `scripts/install.sh` claims
"generate router.env via `upb sync`" — that generation code does not exist in
the CLI. On a fresh macOS install, the router would have no env file.

### Ollama plan limits are real and immediate

`ollama-cloud/deepseek-v4-pro` returns:

```
this model is not included in your free usage... Try gemma4:31b-cloud
```

The router forwarded it correctly — this is an upstream plan error, not a
routing bug. The free plan covers `gemma4:31b` and `minimax-m3.1-flash`; the
big models (`deepseek-v4-pro`, `minimax-m3`) are metered. `minimax-m3.1-flash`
returns HTTP 402 (not in free plan) even though the model exists.

**This is exactly what the registry is for** — `upb registry drift` would flag
it, but only once `upb` is deployed and pointed at the live endpoint.

## What deploying this on macOS needs

1. **Deploy the CLI**: `install -m 0755 cli/upb ~/bin/upb` (or add
   `~/projetos/hub/upb/cli` to PATH).
2. **Generate `router.env` / `providers.yaml`** from `routes.yaml` — this
   converter does not exist yet. It is the real missing piece.
3. **A launchd agent** instead of systemd. `WORKLOG.md` lists
   "macOS deployment support" as an open item; `scripts/install.sh` assumes
   Linux (`systemctl --user`, `apt`).
4. **Decide the model mapping**: the router speaks `provider/model` prefixes;
   Hermes needs the same names in `custom_providers`.
5. **Point Hermes at it**: add the `upb-router` custom provider and switch
   `model.provider`.
6. **Fix the placeholder keys** — `MISTRAL_API_KEY` at minimum, or disable the
   provider so it stops looking configured.

Steps 2 and 3 are the blockers. Steps 1, 4, 5, 6 are configuration.

## What was deliberately NOT changed

The test used a scratch `HERMES_HOME` and a temporary `providers.yaml` in
`/tmp`. The real `~/.hermes/config.yaml` still declares only the two
`Modelos.ai.ulusofona.pt` custom providers and has no reference to upb, 8705
or 8799. The test router was stopped.

Nothing about the live setup was modified.
