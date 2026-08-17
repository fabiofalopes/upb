# upb — Universal Provider Bridge

**upb** makes Claude Code provider-agnostic. It is a dual-intake translation
proxy (Anthropic Messages API ⇄ OpenAI Chat Completions), a route-control CLI,
and a single-source-of-truth key manager in one package. You point Claude Code
at a local proxy exactly once; after that, the upstream provider becomes a
config choice. Route to Alibaba Token Plan, Z.AI, DeepSeek, LiteLLM, Ollama,
PrimeIntellect, OpenCode Zen, or any other OpenAI-compatible endpoint — without
touching your client again.

The practical effect: Claude Code stops being hardwired to Anthropic. You get
one central provider tool for your whole workflow, and you can move fast —
swap models, A/B providers, or fall back to a free tier by editing one YAML
file, not by rewriting your setup.

## Why

Two problems, one bridge:

1. **Claude Code only speaks the Anthropic Messages API** and expects
   `claude-*` model names. It cannot talk to an OpenAI-compatible endpoint
   directly.
2. **Every provider is a snowflake** — its own base URL, auth scheme, model
   ids, and quirks. Wiring each one by hand is a maintenance tax.

upb centralizes the four things that differ per provider — **protocol
translation, routing, key management, and usage tracking** — behind a single
local endpoint. The provider stops being a rewrite and becomes a line of config.
This is deliberately built for experimentation: breaking things in a sandbox
to see which model actually codes better is a feature, not a risk.

## Architecture

The router is a **dual-intake proxy**: it accepts both API dialects and routes
by model prefix or a `claude-*` model map.

```
 Claude Code ──POST /v1/messages──────────────┐
                                              │     ┌─────────────────────────┐
 OpenCode ────POST /v1/chat/completions───────┼────▶│  upb router  :8705      │──▶ Alibaba Token Plan
                                              │     │  translate · route ·    │──▶ Z.AI / DeepSeek
 any agent ───POST /v1/chat/completions───────┘     │  retry · log usage      │──▶ LiteLLM / Ollama / …
                                                    └─────────────────────────┘
```

Anthropic-format requests are translated to OpenAI format on the way out and
back on the way in, including streaming SSE. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design (translation
layer, streaming pipeline, auth model, retry logic).

## Quick start

Requirements: Linux, **Node.js 22+**, **Python 3.10+** with `yaml`. The
installer can fetch Node and PyYAML best-effort if they are missing.

```bash
git clone <this-repo> upb && cd upb

./scripts/install.sh --dry-run   # review the full plan, change nothing
./scripts/install.sh             # build router, install CLI, wire Claude Code

$EDITOR ~/.config/upb/secrets.env   # add your provider keys
upb sync                            # pull keys -> regenerate router.env
systemctl --user restart upb-router
```

The installer builds the router, installs the `upb` CLI, scaffolds config,
generates `router.env`, installs a systemd user service, and points Claude Code
at the proxy (backing up your existing settings first). Always run `--dry-run`
first to see exactly what will happen. Full walkthrough:
[docs/SETUP.md](docs/SETUP.md).

## Install modes

The installer is idempotent and handles both a fresh box and an existing Claude
Code install:

| Mode | What happens |
|------|--------------|
| **From scratch** | Builds everything, creates `~/.config/upb/`, creates `~/.claude/settings.json` with just the proxy env block. |
| **Take over / extend** | Detects an existing `~/.claude/settings.json`, backs it up to `settings.json.upb-backup-<epoch>`, and **merges** the proxy env block — all other settings and env vars are preserved, never clobbered. |

Useful flags: `--dry-run` (plan only), `--no-claude` (skip the Claude Code
takeover), `--no-systemd` (skip the service), `--skip-deps` (don't install
Node/PyYAML), `--prefix <dir>` (router runtime dir), `--force` (overwrite
existing config after backing it up). Full reference in
[docs/SETUP.md](docs/SETUP.md#flag-reference).

## CLI reference

`upb` reads `~/.config/upb/routes.yaml` (override with `$UPB_ROUTES`).

| Command | What it does |
|---------|--------------|
| `upb list [--all] [--json]` | Eligible routes (or everything with `--all`) |
| `upb status [--json]` | Key resolution + live endpoint health per provider |
| `upb run ROUTE [-- ARGS...]` | Launch `claude` through a route (`default`, `provider`, or `provider/model`) |
| `upb stop [ROUTE \| --all]` | Stop proxies spawned by `upb` (never the systemd one) |
| `upb default` | Show the default route |
| `upb doctor` | Config, keys, ports, binaries, hygiene checks |
| `upb models PROVIDER [--refresh]` | List a provider's models (live fetch for `catalog: live`) |
| `upb sync [--full]` | Pull keys → `secrets.env` → generate/update `router.env` |
| `upb env` | Print shell exports pointing at the persistent router |

Two commands deserve emphasis:

- **`upb sync`** is the key pipeline. It pulls keys from the places they live
  (OpenCode `auth.json` / `opencode.json`, your environment), writes them to
  `secrets.env`, and generates `router.env` — the file that drives the router
  in single-provider mode. **`upb sync --full`** regenerates `router.env` from
  scratch instead of updating it in place.
- **`upb env`** prints `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`,
  `OPENAI_BASE_URL`, and `OPENAI_API_KEY` so any other tool can target the
  proxy: `eval "$(upb env)"`.

Exit codes: `0` ok · `2` config/usage error · `3` no eligible route · `4` spawn failed.

## Usage tracking

Every proxied request is appended to a JSONL log (`usage.jsonl` in the router's
working directory; override with `USAGE_LOG`). Each entry records timestamp,
provider, model, wire model, prompt/completion/total tokens, and whether it
streamed. Query the live aggregate:

```bash
curl -s http://127.0.0.1:8705/usage
```

Returns totals plus breakdowns by provider and by model — handy when you are
evaluating which provider earns its keep.

When a model carries a `pricing` block in `routes.yaml` (`input_per_1m` /
`output_per_1m`, USD per 1M tokens), each log entry also gets a computed
`cost_usd` (`null` for unpriced models), and `/usage` reports cost totals —
overall plus per provider and per model. Legacy log lines without `cost_usd`
still aggregate fine (they count tokens, add $0).

## Provider support

Providers are declared in `~/.config/upb/routes.yaml`. `kind: upb` routes go
through the translation proxy; `kind: anthropic-native` providers speak the
Anthropic protocol directly and are passed through without a local proxy.

| Provider | Kind | Key required | Notes |
|----------|------|:---:|-------|
| `alibaba` | upb | yes | Alibaba Token Plan; per-model port routing |
| `zai` | anthropic-native | yes | Z.AI coding plan (GLM family) |
| `deepseek` | anthropic-native | yes | Native Anthropic-protocol endpoint |
| `litellm` | upb | yes | LiteLLM gateway (multi-model) |
| `prime-intellect` | upb | yes | Pay-per-use, `catalog: live` (explicit runs only) |
| `zen` | upb | no | OpenCode Zen free tier |
| `mistral` | upb | yes | Vibe subscription; UA header required |
| `ollama` | upb | yes | Local or cloud Ollama |

Keys are referenced by env-var name in `routes.yaml` and resolved from
`secrets.env` at runtime — a raw key never lives in YAML.

## Uninstall

```bash
./scripts/uninstall.sh           # stop service, remove CLI + router runtime
./scripts/uninstall.sh --purge   # also remove ~/.config/upb (keys included)
```

Config and keys are **preserved by default**. `~/.claude/settings.json` is
never removed automatically — the uninstaller prints how to restore it from the
`.upb-backup` created during install. `--dry-run` is supported.

## Repository layout

```
router/      TypeScript dual-intake proxy (src/, package.json, tsconfig.json)
cli/         upb — Python route-control CLI
config/      Example config (routes.yaml, secrets.env, systemd service)
docs/        ARCHITECTURE.md, SETUP.md
scripts/     install.sh, uninstall.sh
WORKLOG.md   Multi-session coordination hub (shared backlog + session log)
```

## Contributing / multi-session work

This project is coordinated across sessions via [`WORKLOG.md`](WORKLOG.md) — a
shared backlog, in-progress/done tracker, and session log. To contribute: read
`WORKLOG.md` first, check *In progress* (don't duplicate), claim an *Open*
item, work in small commits, and log it in the session-log table. Ground rules
(secrets never in the repo, don't break the live system, verify before marking
Done) are in the WORKLOG header.

## License

[MIT](LICENSE) — copyright 2026 ken.
