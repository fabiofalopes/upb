#!/usr/bin/env bash
# upb installer — copies the CLI and scaffolds config.
# Run from the repository root: ./scripts/install.sh
set -euo pipefail

# Resolve repo root (parent of this script's directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BIN_DIR="${HOME}/bin"
CONFIG_DIR="${HOME}/.config/upb"

echo "upb installer"
echo "  repo root: ${REPO_ROOT}"
echo

# 1. Install the CLI
mkdir -p "${BIN_DIR}"
install -m 0755 "${REPO_ROOT}/cli/upb" "${BIN_DIR}/upb"
echo "  installed  ${BIN_DIR}/upb"

# 2. Create config directory
mkdir -p "${CONFIG_DIR}"
echo "  created    ${CONFIG_DIR}/"

# 3. Copy config examples (only if no existing config)
if [[ ! -f "${CONFIG_DIR}/routes.yaml" ]]; then
  cp "${REPO_ROOT}/config/routes.yaml.example" "${CONFIG_DIR}/routes.yaml"
  echo "  created    ${CONFIG_DIR}/routes.yaml (from example — edit to customize)"
else
  echo "  kept       ${CONFIG_DIR}/routes.yaml (already exists)"
fi

if [[ ! -f "${CONFIG_DIR}/secrets.env" ]]; then
  cp "${REPO_ROOT}/config/secrets.env.example" "${CONFIG_DIR}/secrets.env"
  chmod 600 "${CONFIG_DIR}/secrets.env"
  echo "  created    ${CONFIG_DIR}/secrets.env (chmod 600 — add your keys)"
else
  echo "  kept       ${CONFIG_DIR}/secrets.env (already exists)"
fi

echo
echo "Next steps:"
echo "  1. Make sure ${BIN_DIR} is on your PATH."
echo "  2. Add your provider keys:  \$EDITOR ${CONFIG_DIR}/secrets.env"
echo "  3. Customize routes:        \$EDITOR ${CONFIG_DIR}/routes.yaml"
echo "  4. Build & run the router:  cd router && npm install && npm run build && npm start"
echo "  5. Verify:                  upb doctor"
