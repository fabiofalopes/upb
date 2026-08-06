#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# upb installer — reproduces the full live setup from scratch, or takes over
# and extends an existing Claude Code install.
#
# Idempotent and non-destructive: never deletes user config, always backs up
# ~/.claude/settings.json before touching it, and every mutating operation
# goes through run() so --dry-run shows the complete plan without changing
# anything.
#
# Usage: ./scripts/install.sh [flags]
#   --dry-run             print every action, change nothing
#   --prefix <dir>        router runtime dir   (default: ~/.local/share/upb)
#   --config-dir <dir>    config dir           (default: ~/.config/upb)
#   --bin-dir <dir>       CLI install dir      (default: ~/bin)
#   --port <n>            router listen port   (default: 8705)
#   --model <name>        default model for Claude takeover (default: derived)
#   --skip-deps           don't install node / python3-yaml
#   --no-systemd          skip user-service install
#   --no-claude           skip Claude Code takeover
#   --force               allow overwriting existing config (backs up first)
#   -h, --help            this help
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── colors ──
if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'; C_BOLD=$'\033[1m'; C_RESET=$'\033[0m'
else
  C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_BOLD=""; C_RESET=""
fi

# ── helpers ──
log()   { printf '%s%s%s\n' "$C_BLUE"   "$*" "$C_RESET"; }
phase() { printf '\n%s── %s ──%s\n' "$C_BOLD" "$*" "$C_RESET"; }
ok()    { printf '  %s✓%s %s\n' "$C_GREEN"  "$C_RESET" "$*"; }
warn()  { printf '  %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
err()   { printf '  %s✗%s %s\n' "$C_RED"    "$C_RESET" "$*" >&2; }

DRY_RUN=0
# run <cmd...> — execute a command, or print it in dry-run mode.
run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '  %s[dry-run]%s %s\n' "$C_YELLOW" "$C_RESET" "$*"
    return 0
  fi
  "$@"
}

usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; }

# ── flags ──
PREFIX="${HOME}/.local/share/upb"
CONFIG_DIR="${HOME}/.config/upb"
BIN_DIR="${HOME}/bin"
PORT=8705
MODEL_OVERRIDE=""
SKIP_DEPS=0
NO_SYSTEMD=0
NO_CLAUDE=0
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)     DRY_RUN=1; shift ;;
    --prefix)      PREFIX="${2:?--prefix needs a value}"; shift 2 ;;
    --config-dir)  CONFIG_DIR="${2:?--config-dir needs a value}"; shift 2 ;;
    --bin-dir)     BIN_DIR="${2:?--bin-dir needs a value}"; shift 2 ;;
    --port)        PORT="${2:?--port needs a value}"; shift 2 ;;
    --model)       MODEL_OVERRIDE="${2:?--model needs a value}"; shift 2 ;;
    --skip-deps)   SKIP_DEPS=1; shift ;;
    --no-systemd)  NO_SYSTEMD=1; shift ;;
    --no-claude)   NO_CLAUDE=1; shift ;;
    --force)       FORCE=1; shift ;;
    -h|--help)     usage; exit 0 ;;
    *) err "unknown flag: $1"; echo; usage; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROUTER_DEST="${PREFIX}/router"
ROUTER_ENV="${CONFIG_DIR}/router.env"
SETTINGS_JSON="${HOME}/.claude/settings.json"
SERVICE_NAME="upb-router.service"
SERVICE_FILE="${HOME}/.config/systemd/user/${SERVICE_NAME}"

printf '%supb installer%s\n' "$C_BOLD" "$C_RESET"
[[ $DRY_RUN -eq 1 ]] && printf '%sDRY RUN — nothing will be changed%s\n' "$C_YELLOW" "$C_RESET"
log "repo root:   ${REPO_ROOT}"
log "prefix:      ${PREFIX}"
log "config dir:  ${CONFIG_DIR}"
log "bin dir:     ${BIN_DIR}"
log "port:        ${PORT}"

# ─────────────────────────────────────────────────────────────────────────────
phase "Phase 0 — Preflight & detection"

HAVE_NODE=0; NODE_VER="(none)"; NODE_BIN=""
if command -v node >/dev/null 2>&1; then
  NODE_VER="$(node --version 2>/dev/null || echo unknown)"
  NODE_BIN="$(command -v node)"
  major="${NODE_VER#v}"; major="${major%%.*}"
  [[ "${major}" =~ ^[0-9]+$ ]] && (( major >= 22 )) && HAVE_NODE=1
fi
HAVE_PYYAML=0
python3 -c "import yaml" >/dev/null 2>&1 && HAVE_PYYAML=1
HAVE_CLAUDE=0
command -v claude >/dev/null 2>&1 && HAVE_CLAUDE=1

printf '  node:                 %s\n' "$NODE_VER"
printf '  python3 + yaml:       %s\n' "$( [[ $HAVE_PYYAML -eq 1 ]] && echo OK || echo MISSING )"
printf '  claude binary:        %s\n' "$( [[ $HAVE_CLAUDE -eq 1 ]] && echo "$(command -v claude)" || echo 'not found' )"
printf '  existing upb CLI:     %s\n' "$( [[ -x "${BIN_DIR}/upb" ]] && echo "${BIN_DIR}/upb" || echo 'not installed' )"
printf '  existing config dir:  %s\n' "$( [[ -d "${CONFIG_DIR}" ]] && echo "${CONFIG_DIR}" || echo 'not present' )"
printf '  existing router:      %s\n' "$( [[ -f "${ROUTER_DEST}/dist/index.js" ]] && echo "${ROUTER_DEST}" || echo 'not built' )"
printf '  systemd service:      %s\n' "$( [[ -f "${SERVICE_FILE}" ]] && echo "${SERVICE_FILE}" || echo 'not installed' )"
printf '  claude settings.json: %s\n' "$( [[ -f "${SETTINGS_JSON}" ]] && echo "${SETTINGS_JSON}" || echo 'not present' )"

if [[ $DRY_RUN -eq 1 ]]; then
  echo
  log "Plan (dry-run):"
  [[ $SKIP_DEPS -eq 0 ]] && log "  1. ensure Node >= 22 and python3-yaml"
  log "  2. copy router source → ${ROUTER_DEST}, npm install, npm run build"
  log "  3. install CLI → ${BIN_DIR}/upb"
  log "  4. scaffold config in ${CONFIG_DIR} (non-destructive)"
  log "  5. generate ${ROUTER_ENV} via 'upb sync'"
  [[ $NO_SYSTEMD -eq 0 ]] && log "  6. install + start systemd user service ${SERVICE_NAME}"
  [[ $NO_CLAUDE -eq 0 ]]  && log "  7. merge proxy env into ${SETTINGS_JSON} (backup first)"
  log "  8. verify /health and print summary"
fi

# ─────────────────────────────────────────────────────────────────────────────
phase "Phase 1 — Dependencies"
if [[ $SKIP_DEPS -eq 1 ]]; then
  log "skipped (--skip-deps)"
else
  # Node >= 22
  if [[ $HAVE_NODE -eq 1 ]]; then
    ok "node ${NODE_VER} already satisfies >= 22"
  else
    warn "node >= 22 not found (found: ${NODE_VER}) — attempting best-effort install"
    NODE_ARCH=""
    case "$(uname -m)" in
      x86_64)        NODE_ARCH="x64" ;;
      aarch64|arm64) NODE_ARCH="arm64" ;;
      *) warn "unsupported architecture $(uname -m) for Node tarball" ;;
    esac
    NODE_DL_VER="v22.11.0"
    NODE_DEST="${PREFIX}/node"
    if [[ -n "$NODE_ARCH" ]]; then
      NODE_URL="https://nodejs.org/dist/${NODE_DL_VER}/node-${NODE_DL_VER}-linux-${NODE_ARCH}.tar.xz"
      run mkdir -p "$NODE_DEST"
      if run bash -c "curl -fsSL '${NODE_URL}' | tar -xJ -C '${NODE_DEST}' --strip-components=1"; then
        NODE_BIN="${NODE_DEST}/bin/node"
        ok "installed Node ${NODE_DL_VER} → ${NODE_DEST}"
      else
        NODE_BIN=""
      fi
    fi
    if [[ -z "${NODE_BIN}" || ! -x "${NODE_BIN}" ]] && [[ $DRY_RUN -eq 0 ]]; then
      if ! command -v node >/dev/null 2>&1; then
        err "Node.js is required but could not be installed."
        err "Install Node >= 22 manually (https://nodejs.org) and re-run."
        exit 1
      fi
      warn "falling back to node on PATH: $(command -v node)"
      NODE_BIN="$(command -v node)"
    fi
  fi
  [[ $DRY_RUN -eq 1 && -z "$NODE_BIN" ]] && NODE_BIN="node"

  # python3-yaml
  if [[ $HAVE_PYYAML -eq 1 ]]; then
    ok "python3-yaml present"
  else
    warn "python3-yaml missing — attempting best-effort install"
    if command -v apt-get >/dev/null 2>&1; then
      run sudo apt-get install -y python3-yaml || warn "apt-get install python3-yaml failed"
    elif command -v pip3 >/dev/null 2>&1; then
      run pip3 install --user pyyaml || warn "pip3 install pyyaml failed"
    fi
    python3 -c "import yaml" >/dev/null 2>&1 \
      && ok "python3-yaml installed" \
      || warn "python3-yaml still missing — the upb CLI needs it (apt install python3-yaml)"
  fi
fi

# Derive npm next to node
if [[ "${NODE_BIN}" == */* && -x "$(dirname "${NODE_BIN}")/npm" ]]; then
  NPM_BIN="$(dirname "${NODE_BIN}")/npm"
else
  NPM_BIN="$(command -v npm || echo npm)"
fi

# ─────────────────────────────────────────────────────────────────────────────
phase "Phase 2 — Install router"
run mkdir -p "$ROUTER_DEST"
if [[ $DRY_RUN -eq 1 ]]; then
  run rsync -a --exclude node_modules --exclude dist "${REPO_ROOT}/router/" "${ROUTER_DEST}/"
else
  rsync -a --exclude node_modules --exclude dist "${REPO_ROOT}/router/" "${ROUTER_DEST}/"
  ok "copied router source → ${ROUTER_DEST}"
fi
log "npm install && npm run build (this may take a minute)…"
run bash -c "cd '${ROUTER_DEST}' && '${NPM_BIN}' install --no-audit --no-fund && '${NPM_BIN}' run build"
if [[ $DRY_RUN -eq 0 ]]; then
  if [[ ! -f "${ROUTER_DEST}/dist/index.js" ]]; then
    err "router build failed: ${ROUTER_DEST}/dist/index.js not found"
    exit 1
  fi
  ok "router built: ${ROUTER_DEST}/dist/index.js"
fi

# ─────────────────────────────────────────────────────────────────────────────
phase "Phase 3 — Install CLI"
run mkdir -p "$BIN_DIR"
run install -m 0755 "${REPO_ROOT}/cli/upb" "${BIN_DIR}/upb"
ok "installed ${BIN_DIR}/upb"
case ":${PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *) warn "${BIN_DIR} is not in PATH — add: export PATH=\"${BIN_DIR}:\$PATH\"" ;;
esac

# ─────────────────────────────────────────────────────────────────────────────
phase "Phase 4 — Scaffold config (non-destructive)"
run mkdir -p "$CONFIG_DIR"

scaffold() { # <src-example> <dest> <mode>
  local src="$1" dest="$2" mode="$3"
  if [[ -f "$dest" ]]; then
    if [[ $FORCE -eq 1 ]]; then
      local backup="${dest}.upb-backup-$(date +%s)"
      run cp "$dest" "$backup"
      run cp "$src" "$dest"
      [[ "$mode" == 600 ]] && run chmod 600 "$dest"
      ok "replaced $(basename "$dest") (backup: ${backup})"
    else
      ok "kept existing $(basename "$dest")"
    fi
  else
    run cp "$src" "$dest"
    [[ "$mode" == 600 ]] && run chmod 600 "$dest"
    ok "created $(basename "$dest") from example"
  fi
}
scaffold "${REPO_ROOT}/config/routes.yaml.example" "${CONFIG_DIR}/routes.yaml" 644
scaffold "${REPO_ROOT}/config/secrets.env.example" "${CONFIG_DIR}/secrets.env" 600

# ─────────────────────────────────────────────────────────────────────────────
phase "Phase 5 — Generate router.env"
log "running: UPB_ROUTER_ENV=${ROUTER_ENV} upb sync (generates router.env)"
run env UPB_ROUTES="${CONFIG_DIR}/routes.yaml" \
        UPB_SECRETS="${CONFIG_DIR}/secrets.env" \
        UPB_ROUTER_ENV="${ROUTER_ENV}" \
        UPB_CACHE="${HOME}/.cache/upb" \
    "${BIN_DIR}/upb" sync

# Align router.env's PORT with the --port flag (sync derives it from
# routes.yaml defaults.port, which may differ). router.env is a generated
# file we own, so a targeted rewrite of the PORT line is safe.
if [[ $DRY_RUN -eq 0 && -f "$ROUTER_ENV" ]]; then
  if grep -q '^PORT=' "$ROUTER_ENV"; then
    sed -i "s/^PORT=.*/PORT=${PORT}/" "$ROUTER_ENV"
  else
    printf 'PORT=%s\n' "$PORT" >> "$ROUTER_ENV"
  fi
fi

# Capture LOCAL_SECRET + default model from the generated router.env / routes.yaml
LOCAL_SECRET=""
DEFAULT_MODEL=""
if [[ $DRY_RUN -eq 0 && -f "$ROUTER_ENV" ]]; then
  LOCAL_SECRET="$(sed -n 's/^LOCAL_SECRET=//p' "$ROUTER_ENV" | tr -d "'\"")"
  ok "router.env present (LOCAL_SECRET captured)"
else
  LOCAL_SECRET="<LOCAL_SECRET from router.env>"
fi

# Derive default model from routes.yaml if not overridden
if [[ -z "$MODEL_OVERRIDE" && $DRY_RUN -eq 0 && -f "${CONFIG_DIR}/routes.yaml" ]]; then
  DEFAULT_MODEL="$(python3 - "${CONFIG_DIR}/routes.yaml" <<'PY' 2>/dev/null || true
import sys, yaml
from datetime import date
cfg = yaml.safe_load(open(sys.argv[1]))
provs = cfg.get("providers", {})
def skipped(p):
    if not p.get("enabled", True): return True
    until = p.get("active_until")
    if until:
        try:
            if date.today() > date.fromisoformat(str(until).strip()): return True
        except ValueError: pass
    return False
ranked = sorted(provs.items(), key=lambda kv: (kv[1].get("priority", 50), kv[0]))
for name, p in ranked:
    if p.get("catalog") == "live" or skipped(p): continue
    models = p.get("models") or {}
    if not models: continue
    primary = next((m for m, mc in models.items() if (mc or {}).get("primary")), None)
    print(primary or next(iter(models))); break
PY
  )"
fi
[[ -n "$MODEL_OVERRIDE" ]] && DEFAULT_MODEL="$MODEL_OVERRIDE"
[[ -z "$DEFAULT_MODEL" ]] && DEFAULT_MODEL="<default-model>"
log "default model for Claude takeover: ${DEFAULT_MODEL}"

# ─────────────────────────────────────────────────────────────────────────────
phase "Phase 6 — systemd user service"
if [[ $NO_SYSTEMD -eq 1 ]]; then
  log "skipped (--no-systemd)"
else
  SYSTEMD_OK=0
  if systemctl --user status >/dev/null 2>&1; then SYSTEMD_OK=1; fi
  if [[ $SYSTEMD_OK -eq 0 && $DRY_RUN -eq 0 ]]; then
    warn "systemctl --user not available (container?). Fallback — run manually:"
    warn "  nohup ${NODE_BIN} ${ROUTER_DEST}/dist/index.js > /tmp/upb-router.log 2>&1 &"
  else
    run mkdir -p "${HOME}/.config/systemd/user"
    if [[ $DRY_RUN -eq 1 ]]; then
      run render "${REPO_ROOT}/config/universal-router.service.example" "->" "$SERVICE_FILE"
    else
      sed -e "s|^WorkingDirectory=.*|WorkingDirectory=${ROUTER_DEST}|" \
          -e "s|^EnvironmentFile=.*|EnvironmentFile=${ROUTER_ENV}|" \
          -e "s|^ExecStart=.*|ExecStart=${NODE_BIN} ${ROUTER_DEST}/dist/index.js|" \
          "${REPO_ROOT}/config/universal-router.service.example" > "$SERVICE_FILE"
      ok "rendered ${SERVICE_FILE}"
    fi
    if [[ -f "$SERVICE_FILE" && $FORCE -eq 0 && $DRY_RUN -eq 0 ]] \
       && systemctl --user is-enabled "$SERVICE_NAME" >/dev/null 2>&1; then
      ok "service already enabled — leaving as-is (use --force to re-enable)"
    else
      run systemctl --user daemon-reload
      run systemctl --user enable --now "$SERVICE_NAME"
      ok "enabled + started ${SERVICE_NAME}"
    fi
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
phase "Phase 7 — Claude Code takeover/extend"
if [[ $NO_CLAUDE -eq 1 ]]; then
  log "skipped (--no-claude)"
else
  if [[ $DRY_RUN -eq 1 ]]; then
    [[ -f "$SETTINGS_JSON" ]] && run backup "$SETTINGS_JSON" "->" "${SETTINGS_JSON}.upb-backup-<epoch>"
    run merge-env "$SETTINGS_JSON" "ANTHROPIC_BASE_URL=http://127.0.0.1:${PORT}" \
        "ANTHROPIC_AUTH_TOKEN=${LOCAL_SECRET}" "ANTHROPIC_MODEL=${DEFAULT_MODEL}" \
        "CLAUDE_CODE_SUBAGENT_MODEL=${DEFAULT_MODEL}"
  else
    mkdir -p "$(dirname "$SETTINGS_JSON")"
    if [[ -f "$SETTINGS_JSON" ]]; then
      BACKUP="${SETTINGS_JSON}.upb-backup-$(date +%s)"
      cp "$SETTINGS_JSON" "$BACKUP"
      ok "backed up settings.json → ${BACKUP}"
    fi
    python3 - "$SETTINGS_JSON" "$PORT" "$LOCAL_SECRET" "$DEFAULT_MODEL" <<'PY'
import json, sys
path, port, secret, model = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
try:
    with open(path) as f: data = json.load(f)
    if not isinstance(data, dict): data = {}
except (FileNotFoundError, json.JSONDecodeError):
    data = {}
env = data.get("env")
if not isinstance(env, dict): env = {}
env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
env["ANTHROPIC_AUTH_TOKEN"] = secret
env["ANTHROPIC_MODEL"] = model
env["CLAUDE_CODE_SUBAGENT_MODEL"] = model
data["env"] = env
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("  \u2713 merged env into", path)
PY
    ok "Claude Code pointed at http://127.0.0.1:${PORT} (model: ${DEFAULT_MODEL})"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
phase "Phase 8 — Verify"
if [[ $DRY_RUN -eq 1 ]]; then
  run curl -s "http://127.0.0.1:${PORT}/health"
  run "${BIN_DIR}/upb" list
else
  sleep 1
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    ok "router healthy on :${PORT}"
    curl -s "http://127.0.0.1:${PORT}/health" | python3 -m json.tool 2>/dev/null | sed 's/^/    /' || true
  else
    warn "router not responding on :${PORT} yet. Troubleshoot:"
    warn "  systemctl --user status ${SERVICE_NAME}"
    warn "  journalctl --user -u ${SERVICE_NAME} -n 20"
  fi
  if [[ -x "${BIN_DIR}/upb" ]]; then
    UPB_ROUTES="${CONFIG_DIR}/routes.yaml" UPB_SECRETS="${CONFIG_DIR}/secrets.env" \
    UPB_ROUTER_ENV="${ROUTER_ENV}" "${BIN_DIR}/upb" list 2>/dev/null | sed 's/^/    /' || true
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
phase "Summary"
log "router:      ${ROUTER_DEST}"
log "CLI:         ${BIN_DIR}/upb"
log "config:      ${CONFIG_DIR}"
log "router.env:  ${ROUTER_ENV}"
log "service:     ${SERVICE_NAME} (port ${PORT})"
log "Claude Code: ${SETTINGS_JSON}"
echo
log "Next steps:"
log "  1. Add real keys:   \$EDITOR ${CONFIG_DIR}/secrets.env"
log "  2. Re-sync:         ${BIN_DIR}/upb sync"
log "  3. Restart service: systemctl --user restart ${SERVICE_NAME}"
log "  4. Verify:          ${BIN_DIR}/upb doctor"
echo
ok "install complete$([[ $DRY_RUN -eq 1 ]] && echo ' (dry-run — nothing changed)')"
