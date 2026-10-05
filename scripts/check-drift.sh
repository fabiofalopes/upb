#!/usr/bin/env bash
# check-drift.sh — guard against upb two-copy drift.
# The router's single home is ~/projects/upb (source + runtime).
# Exit 1 with an error message if drift is detected.
set -u

FAIL=0

# 1. ~/bin/upb must be a symlink to the repo CLI
LINK_TARGET="$(readlink ~/bin/upb 2>/dev/null || true)"
case "$LINK_TARGET" in
  *projects/upb/cli/upb) ;;
  *)
    echo "DRIFT: ~/bin/upb does not point at ~/projects/upb/cli/upb (got: '${LINK_TARGET:-missing}')" >&2
    FAIL=1
    ;;
esac

# 2. proxy.dir in routes.yaml must be the repo router
PROXY_DIR="$(grep -E '^\s*dir:' ~/.config/upb/routes.yaml 2>/dev/null | head -1 | sed 's/.*dir:\s*//' | tr -d ' ' || true)"
case "$PROXY_DIR" in
  *projects/upb/router) ;;
  *)
    echo "DRIFT: proxy.dir in ~/.config/upb/routes.yaml is '${PROXY_DIR:-missing}', expected ~/projects/upb/router" >&2
    FAIL=1
    ;;
esac

# 3. The old deployed copy must stay gone
if [ -e ~/shared-local/reports/claude-universal/dist/index.js ]; then
  echo "DRIFT: stale deployed copy ~/shared-local/reports/claude-universal/ has reappeared" >&2
  FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
  echo "upb drift check: OK (single home ~/projects/upb)"
fi
exit "$FAIL"
