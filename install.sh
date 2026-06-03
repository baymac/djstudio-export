#!/usr/bin/env bash
# One-line installer for dj.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/baymac/dj/main/install.sh | bash
#
# Installs the latest GitHub Release via uv tool install.
# Requirements: macOS, uv (https://astral.sh/uv/install.sh).

set -euo pipefail

REPO="baymac/dj"
INSTALL_URL="git+https://github.com/${REPO}.git"

# ── OS check ────────────────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
  echo "dj requires macOS." >&2
  exit 1
fi

# ── uv check ────────────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
  echo "uv is required but not found."
  echo "Install it first: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

# ── Resolve latest release tag ──────────────────────────────────────────────
echo "Fetching latest release tag from github.com/${REPO}…"
LATEST=$(curl -fsSL \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${REPO}/releases/latest" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])" 2>/dev/null || true)

if [[ -z "$LATEST" ]]; then
  echo "Could not determine the latest release tag."
  echo "Check your network or install a specific version:"
  echo "  uv tool install ${INSTALL_URL}@<tag>"
  exit 1
fi

echo "Installing dj ${LATEST}…"

# ── Check for stale dj-tools dist and warn ──────────────────────────────────
if uv tool list 2>/dev/null | grep -q "^dj-tools"; then
  echo ""
  echo "WARNING: old 'dj-tools' tool is installed."
  echo "  Remove it to avoid PATH conflicts: uv tool uninstall dj-tools"
  echo ""
fi

# ── Install ─────────────────────────────────────────────────────────────────
uv tool install --force "${INSTALL_URL}@${LATEST}"

echo ""
echo "dj ${LATEST} installed successfully."
echo ""
echo "Next steps:"
echo "  1. Create ~/Music/dj/.env with your Beatport session token:"
echo "       echo 'BEATPORT_SESSION_TOKEN=<token>' >> ~/Music/dj/.env"
echo "  2. Run 'dj doctor' to verify all prerequisites."
echo "  3. Run 'dj --help' to see available commands."
