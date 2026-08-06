# Setup guide

Step-by-step instructions to get the router running and your clients talking to
it. Two paths are covered: installing **from scratch** on a fresh box, and
**taking over** a machine where Claude Code is already installed.

## Prerequisites

- **Linux** with a systemd user session (`systemctl --user` works). Containers
  without a user session are supported via a manual/nohup fallback.
- **Node.js 22+** (the router is ESM TypeScript compiled with `tsc`).
- **Python 3.10+** with `yaml` (for the `upb` CLI). On Debian/Kali:
  `sudo apt install python3-yaml`.
- **git**, and a provider API key for at least one provider you want to use.

The installer will try to install Node and PyYAML for you best-effort if they
are missing. Pass `--skip-deps` to bypass that and manage dependencies yourself.

## Install from scratch

Full walkthrough on a fresh box:

```bash
git clone <this-repo> upb && cd upb

# 1. Review the plan first — prints every action, changes nothing.
./scripts/install.sh --dry-run

# 2. Install for real.
./scripts/install.sh
```

The installer then: builds the router into `~/.local/share/upb/router`,
installs the CLI to `~/bin/upb`, scaffolds `~/.config/upb/`, generates
`~/.config/upb/router.env`, installs + starts the `upb-router.service` user
service, and points Claude Code at the proxy.

```bash
# 3. Add your real provider keys.
$EDITOR ~/.config/upb/secrets.env
chmod 600 ~/.config/upb/secrets.env

# 4. Re-sync so router.env picks up the real keys.
upb sync
systemctl --user restart upb-router

# 5. Verify.
curl -s http://127.0.0.1:8705/health
```

A healthy response looks like `{"status":"ok","service":"universal-provider-router",...}`.

## Take over an existing Claude Code install

If `~/.claude/settings.json` already exists, the installer **extends** it rather
than replacing it:

1. **Detection** — Phase 0 reports `claude settings.json: /home/you/.claude/settings.json`.
2. **Backup** — before touching it, the installer copies it to
   `~/.claude/settings.json.upb-backup-<epoch>`.
3. **Merge** — it sets only four keys inside the `env` block
   (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`,
   `CLAUDE_CODE_SUBAGENT_MODEL`). Every other top-level key and every other env
   var is preserved.

To review what changed, diff the backup against the live file:

```bash
diff ~/.claude/settings.json.upb-backup-* ~/.claude/settings.json
```

To revert, copy the backup back:

```bash
cp ~/.claude/settings.json.upb-backup-<epoch> ~/.claude/settings.json
```

`--force` makes the installer overwrite existing config files (`routes.yaml`,
`secrets.env`) — but it still backs each one up first. Without `--force`,
existing config files are kept untouched.

## Flag reference

### `scripts/install.sh`

| Flag | Default | Meaning |
|------|---------|---------|
| `--dry-run` | off | Print every action, change nothing |
| `--prefix <dir>` | `~/.local/share/upb` | Router runtime install dir |
| `--config-dir <dir>` | `~/.config/upb` | Config dir |
| `--bin-dir <dir>` | `~/bin` | CLI install dir |
| `--port <n>` | `8705` | Router listen port |
| `--model <name>` | derived | Default model for the Claude takeover |
| `--skip-deps` | off | Don't install Node / PyYAML |
| `--no-systemd` | off | Skip user-service install |
| `--no-claude` | off | Skip Claude Code takeover |
| `--force` | off | Overwrite existing config (backs up first) |
| `-h`, `--help` | — | Show help |

### `scripts/uninstall.sh`

| Flag | Default | Meaning |
|------|---------|---------|
| `--dry-run` | off | Print every action, change nothing |
| `--prefix <dir>` | `~/.local/share/upb` | Router runtime dir to remove |
| `--config-dir <dir>` | `~/.config/upb` | Config dir (preserved unless `--purge`) |
| `--bin-dir <dir>` | `~/bin` | CLI dir to remove |
| `--purge` | off | Also remove the config dir (keys included) |
| `-h`, `--help` | — | Show help |

## Key management

`~/.config/upb/secrets.env` is the **single source of truth** for provider keys
(`chmod 600`). `routes.yaml` references keys only by env-var name; a raw key
never lives in YAML.

`upb sync` is the pipeline that keeps everything consistent:

- **Pull** — reads keys from where they already live:
  - OpenCode `~/.local/share/opencode/auth.json` (e.g. `ALIBABA_TOKEN_PLAN_KEY`, `OPENCODE_GO_KEY`)
  - OpenCode `~/.config/opencode/opencode.json` (the LiteLLM `apiKey`)
  - Your environment (`ZAI_API_KEY`, `PRIME_INTELLECT_API_KEY`, `OLLAMA_API_KEY`, `DEEPSEEK_API_KEY`)
- **Write** — merges them into `secrets.env` (`chmod 600`).
- **Push** — generates/updates `~/.config/upb/router.env`, the file that drives
  the router in single-provider mode (`PORT`, `UPB_PROVIDER`, `UPB_BASE_URL`,
  `UPB_API_KEY`, `UPB_MODEL_MAP`, `LOCAL_SECRET`).

`upb sync --full` regenerates `router.env` from scratch. Plain `upb sync`
updates it in place when it already exists.

**`LOCAL_SECRET`** is the shared token that authenticates clients to the proxy.
`upb sync` preserves it across regenerations if `router.env` already has one,
otherwise it generates a stable random value (`upb-local-<hex>`). Claude Code
receives it as `ANTHROPIC_AUTH_TOKEN`.

## Running the router

The installer runs the router as a systemd **user** service named
`upb-router.service`:

```bash
systemctl --user status upb-router
systemctl --user restart upb-router
journalctl --user -u upb-router -n 40        # logs
```

The service loads `router.env` via `EnvironmentFile=`, so the port and provider
come from there. **`PORT`** is set by `upb sync` (from `routes.yaml`
`defaults.port`, defaulting to `8705`) and aligned to `install.sh --port`.

**No systemd?** Run it in the foreground or backgrounded:

```bash
cd ~/.local/share/upb/router
set -a; . ~/.config/upb/router.env; set +a   # load PORT/UPB_* into the env
node dist/index.js                            # foreground
# or: nohup node dist/index.js > /tmp/upb-router.log 2>&1 &
```

## Claude Code integration details

The installer writes four env vars into `~/.claude/settings.json` under `env`:

| Var | Value | Why |
|-----|-------|-----|
| `ANTHROPIC_BASE_URL` | `http://127.0.0.1:<port>` | Point Claude Code at the local proxy instead of Anthropic |
| `ANTHROPIC_AUTH_TOKEN` | the `LOCAL_SECRET` | Authenticate to the proxy's Anthropic intake |
| `ANTHROPIC_MODEL` | default route's model | The upstream model that answers as the "main" model |
| `CLAUDE_CODE_SUBAGENT_MODEL` | default route's model | Model used by Claude Code subagents |

`upb run ROUTE` is the per-invocation alternative: it launches `claude` with the
right environment for one route without editing `settings.json`
(`upb run default`, `upb run zai`, `upb run zai/glm-5.2`).

**Pointing other tools at the proxy.** `upb env` prints exports for both
dialects; eval it in a shell, or paste the equivalent into any tool's config:

```bash
eval "$(upb env)"
# sets ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, OPENAI_BASE_URL, OPENAI_API_KEY
```

For an OpenAI-only client, use `OPENAI_BASE_URL` (the OpenAI intake) and a
provider-prefixed model name to control routing, e.g. `litellm/some-model`.

## Verification & troubleshooting

```bash
curl -s http://127.0.0.1:8705/health   # expect status: ok
upb doctor                              # config, keys, ports, binaries, hygiene
upb list                                # eligible routes
upb status                              # key resolution + live endpoint health
```

Common failures:

- **Port already in use** — pick another with `install.sh --port <n>`, or stop
  the conflicting process. `upb doctor` reports duplicate ports.
- **`node` too old** — the installer needs Node >= 22; install it manually and
  re-run with `--skip-deps`.
- **Missing keys** — `router.env` gets an empty/placeholder `UPB_API_KEY` and
  `upb sync` warns. Add the key to `secrets.env`, then `upb sync` again.
- **Service won't start** — `journalctl --user -u upb-router -n 40`. Usually a
  bad `router.env` (missing key) or a missing `dist/index.js` (re-run install).
- **401 from the router** — the client's token doesn't match `LOCAL_SECRET`.
- **`upb: python3-yaml is required`** — `sudo apt install python3-yaml`.

Note: `upb doctor`'s systemd-awareness line refers, for historical reasons, to a
service named `universal-router`. The installer creates `upb-router.service`, so
use `systemctl --user status upb-router` directly to check the installed service.

## Uninstall

```bash
./scripts/uninstall.sh           # stop service, remove CLI + router runtime
./scripts/uninstall.sh --purge   # also remove ~/.config/upb (keys included)
```

By default your config and keys (`routes.yaml`, `secrets.env`, `router.env`) are
**preserved**. `~/.claude/settings.json` is never removed automatically — the
uninstaller prints the `cp` command to restore it from the `.upb-backup`. Use
`--dry-run` to preview.
