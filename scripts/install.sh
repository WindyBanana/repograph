#!/usr/bin/env bash
# Install repograph so `repograph` is on your PATH.
# Works on macOS and Linux. Prefers pipx, falls back to a symlink into ~/.local/bin.
set -euo pipefail

ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v pipx >/dev/null 2>&1; then
  echo "installing with pipx from $ROOT"
  pipx install --force "$ROOT"
  echo "done — run: repograph scan /path/to/repo"
  exit 0
fi

BIN_DIR="${REPOGRAPH_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
ln -sf "$ROOT/bin/repograph" "$BIN_DIR/repograph"
echo "linked $BIN_DIR/repograph -> $ROOT/bin/repograph"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "note: $BIN_DIR is not on your PATH. Add this to your shell profile:"
     echo "  export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
echo "done — run: repograph scan /path/to/repo"
