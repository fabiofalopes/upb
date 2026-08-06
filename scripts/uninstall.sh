#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# upb uninstaller — safe teardown, mirror of install.sh.
#
# By default this PRESERVES your config and keys (routes.yaml, secrets.env)
# and never touches ~/.claude/settings.json. Pass --purge to also remove the
# config directory. ~/.claude/settings.json is never removed automatically;
# restore it from the .upb-backup created during install instead.
#
# Usage: ./scripts/uninstall.sh [flags]
#   --dry-run            print every action, change nothing
#   --prefix <dir>       router runtime dir   (default: ~/.local/share/upb)
#   --config-dir <dir>   config dir           (default: ~/.config/upb)
#   --bin-dir <dir>      CLI install dir      (default: ~/bin)
#   --purge              also remove the config directory (keys included)
#   -h, --help           this help
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'; C_BOLD=$'\033[1m'; C_RESET=$'\033[0m'
else
  C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_BOLD=""; C_RESET=""
fi

log()   { printf '%s%s%s\n' "$C_BLUE"   "$*" "$C_RESET"; }
phase() { printf '\n%s── %s ──%s\n' "$C_BOLD" "$*" "$C_RESET"; }
ok()    { printf '  %s✓%s %s\n' "$C_GREEN"  "$C_RESET" "$*"; }
warn()  { printf '  %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
err()   { printf '  %s✗%s %s\n' "$C_RED"    "$C_RESET" "$*" >&2; }

DRY_RUN=0
run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '  %s[dry-run]%s %s\n' "$C_YELLOW" "$C_RESET" "$*"
    return 0
  fi
  "$@"
}
usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; }

PREFIX="${HOME}/.local/share/upb"
CONFIG_DIR="${HOME}/.config/upb"
BIN_DIR="${HOME}/bin"
PURGE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)    DRY_RUN=1; shift ;;
    --prefix)     PREFIX="${2:?--prefix needs a value}"; shift 2 ;;
    --config-dir) CONFIG_DIR="${2:?--config-dir needs a value}"; shift 2 ;;
    --bin-dir)    BIN_DIR="${2:?--bin-dir needs a value}"; shift 2 ;;
    --purge)      PURGE=1; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) err "unknown flag: $1"; echo; usage; exit 2 ;;
  esac
done

SERVICE_NAME="upb-router.service"
SERVICE_FILE="${HOME}/.config/systemd/user/${SERVICE_NAME}"
SETTINGS_JSON="${HOME}/.claude/settings.json"

# Refuse to operate on paths that are clearly not upb-owned.
for p in "$PREFIX" "$CONFIG_DIR" "$BIN_DIR"; do
  case "$p" in
    ""|"/"|"$HOME") err "refusing to remove unsafe path: '$p'"; exit 1 ;;
  esac
done

printf '%supb uninstaller%s\n' "$C_BOLD" "$C_RESET"
[[ $DRY_RUN -eq 1 ]] && printf '%sDRY RUN — nothing will be changed%s\n' "$C_YELLOW" "$C_RESET"
log "prefix:     ${PREFIX}"
log "config dir: ${CONFIG_DIR}"
log "bin dir:    ${BIN_DIR}"
log "purge:      $( [[ $PURGE -eq 1 ]] && echo yes || echo no )"

# ── 1. Stop + disable the service ──
phase "Stop & disable service"
if systemctl --user status >/dev/null 2>&1; then
  if systemctl --user list-unit-files "$SERVICE_NAME" 2>/dev/null | grep -q "$SERVICE_NAME"; then
    run systemctl --user stop "$SERVICE_NAME" || true
    run systemctl --user disable "$SERVICE_NAME" || true
    ok "stopped + disabled ${SERVICE_NAME}"
  else
    ok "service ${SERVICE_NAME} not present"
  fi
  if [[ -f "$SERVICE_FILE" ]]; then
    run rm -f "$SERVICE_FILE"
    run systemctl --user daemon-reload || true
    ok "removed ${SERVICE_FILE}"
  else
    ok "no unit file at ${SERVICE_FILE}"
  fi
else
  warn "systemctl --user unavailable — skipping service teardown"
  [[ -f "$SERVICE_FILE" ]] && run rm -f "$SERVICE_FILE"
fi

# ── 2. Remove the CLI ──
phase "Remove CLI"
if [[ -e "${BIN_DIR}/upb" ]]; then
  run rm -f "${BIN_DIR}/upb"
  ok "removed ${BIN_DIR}/upb"
else
  ok "no CLI at ${BIN_DIR}/upb"
fi

# ── 3. Remove the router runtime ──
phase "Remove router runtime"
if [[ -d "$PREFIX" ]]; then
  run rm -rf "$PREFIX"
  ok "removed ${PREFIX}"
else
  ok "no router runtime at ${PREFIX}"
fi

# ── 4. Config: preserve by default, purge on request ──
phase "Config"
if [[ $PURGE -eq 1 ]]; then
  if [[ -d "$CONFIG_DIR" ]]; then
    run rm -rf "$CONFIG_DIR"
    ok "purged ${CONFIG_DIR} (routes.yaml, secrets.env, router.env removed)"
  else
    ok "no config dir at ${CONFIG_DIR}"
  fi
else
  ok "preserved ${CONFIG_DIR} (routes.yaml, secrets.env, router.env kept)"
fi

# ── 5. Claude settings.json — never removed automatically ──
phase "Claude Code settings"
if [[ -f "$SETTINGS_JSON" ]]; then
  warn "left ${SETTINGS_JSON} untouched (never removed automatically)."
  BACKUPS="$(ls -1 "${SETTINGS_JSON}.upb-backup-"* 2>/dev/null || true)"
  if [[ -n "$BACKUPS" ]]; then
    log "To restore your pre-install settings, copy a backup over it, e.g.:"
    log "  cp \"$(echo "$BACKUPS" | tail -1)\" \"${SETTINGS_JSON}\""
  else
    log "No .upb-backup found — edit ${SETTINGS_JSON} and remove the"
    log "env.ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN keys to revert."
  fi
else
  ok "no ${SETTINGS_JSON} present"
fi

echo
ok "uninstall complete$([[ $DRY_RUN -eq 1 ]] && echo ' (dry-run — nothing changed)')"
[[ $PURGE -eq 0 ]] && log "config + keys preserved at ${CONFIG_DIR}"
