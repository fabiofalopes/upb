# Setup guide

Step-by-step instructions to get the router running and your clients talking to it.

## Prerequisites

- **Node.js 22+** (the router is ESM TypeScript compiled with `tsc`)
- **Python 3.10+** with `python3-yaml` (for the `upb` CLI)
- A provider API key for at least one provider you want to use

On Debian/Kali:

```bash
sudo apt install python3-yaml
```

## 1. Install

From the repository root:

```bash
./scripts/install.sh
```

This copies `cli/upb` to `~/bin/upb`, creates `~/.config/upb/`, and installs
the example config files if you don't already have them. Make sure `~/bin` is
on your `PATH`.

## 2. Configure secrets

`secrets.env` is the single source of truth for provider keys. Copy the example
and fill in your keys:

```bash
cp config/secrets.env.example ~/.config/upb/secrets.env
chmod 600 ~/.config/upb/secrets.env
$EDITOR ~/.config/upb/secrets.env
```

Keys are referenced from `providers.yaml` / `routes.yaml` via environment
variables — never paste a raw key into a YAML file.

## 3. Configure routes

Copy the routes example and customize:

```bash
cp config/routes.yaml.example ~/.config/upb/routes.yaml
$EDITOR ~/.config/upb/routes.yaml
```

Set `proxy.dir` to where you keep the router (the `router/` directory) and
`proxy.node` to your Node binary (or just `node` if it's on `PATH`). Define the
providers, models, and ports you want under `providers:`.

## 4. Build and run the router

```bash
cd router
npm install
npm run build
npm start
```

Verify:

```bash
curl -s http://localhost:8443/health
curl -s http://localhost:8443/v1/models
```

For development with auto-reload-from-source:

```bash
npm run dev
```

## 5. Run as a systemd user service

Copy the service template and edit the paths:

```bash
mkdir -p ~/.config/systemd/user
cp config/universal-router.service.example ~/.config/systemd/user/universal-router.service
$EDITOR ~/.config/systemd/user/universal-router.service
```

Set `WorkingDirectory` to your `router/` directory and `EnvironmentFile` to a
file exporting your keys (e.g. `UPB_API_KEY`, `LOCAL_SECRET`, `PORT`). Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now universal-router
systemctl --user status universal-router
```

The `upb` CLI is aware of this service: `upb doctor` reports its state, and
`upb stop` will never kill the systemd-managed proxy.

## 6. Claude Code integration

`upb run` launches `claude` with the right environment automatically:

```bash
upb run default            # highest-priority eligible route
upb run zai                # a specific provider
upb run zai/glm-5.2        # a specific provider/model
```

Under the hood it sets `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` (plus
any `claude_env` overrides from `routes.yaml`) and execs `claude`.

To point a shell at the persistent router manually:

```bash
eval "$(upb env)"
```

Or set the equivalent block in Claude Code's `settings.json` `env` section:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8443",
    "ANTHROPIC_AUTH_TOKEN": "your-local-secret"
  }
}
```

## 7. OpenCode / OpenAI-client integration

Point any OpenAI-compatible client at the OpenAI intake:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8443/v1
export OPENAI_API_KEY=your-local-secret
```

Use a model name with a provider prefix to control routing, e.g.
`litellm/some-model`. `upb env` prints these exports too.

## 8. Key management with `upb sync`

`upb sync` keeps `secrets.env` in sync with the places your keys actually live:

```bash
upb sync
```

It pulls keys from known source stores (e.g. OpenCode's `auth.json` /
`opencode.json` and the environment), writes them to `secrets.env` (`chmod 600`),
and pushes derived files (such as the router env file referenced by
`UPB_ROUTER_ENV`) so the running service picks up rotated keys.

## 9. Verify everything

```bash
upb doctor     # config, keys, ports, binaries, hygiene
upb status     # key resolution + live endpoint health
upb list       # eligible routes
```

## Troubleshooting

- **`upb: python3-yaml is required`** — install `python3-yaml`.
- **Router won't start** — run `npm run build` first; `npm start` runs the
  compiled `dist/index.js`.
- **401 from the router** — your client's API key doesn't match `LOCAL_SECRET`.
- **Wrong model reached** — check the provider prefix and the provider's
  `model_map` in `providers.yaml`.
- **Where did my tokens go?** — `curl -s http://localhost:8443/usage`.
