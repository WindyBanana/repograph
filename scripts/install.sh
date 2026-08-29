#!/usr/bin/env bash
# Install repograph on macOS or Linux.
#
#   ./scripts/install.sh              from a git clone
#   ./scripts/install.sh --binary ./repograph   from a downloaded release build
#
# Puts `repograph` on your PATH and, unless you pass --no-desktop, registers a
# desktop entry (Linux) or an application bundle (macOS) so it can be launched
# without a terminal.
set -euo pipefail

ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${REPOGRAPH_BIN_DIR:-$HOME/.local/bin}"
BINARY=""
DESKTOP=1

while [ $# -gt 0 ]; do
  case "$1" in
    --binary) BINARY="$2"; shift 2 ;;
    --bin-dir) BIN_DIR="$2"; shift 2 ;;
    --no-desktop) DESKTOP=0; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say() { printf '  %s\n' "$*"; }

mkdir -p "$BIN_DIR"

if [ -n "$BINARY" ]; then
  # Installing a downloaded standalone build.
  install -m 755 "$BINARY" "$BIN_DIR/repograph"
  TARGET="$BIN_DIR/repograph"
  say "installed $TARGET"
elif command -v pipx >/dev/null 2>&1; then
  pipx install --force "$ROOT" >/dev/null
  TARGET="$(command -v repograph || echo "$HOME/.local/bin/repograph")"
  say "installed with pipx: $TARGET"
else
  ln -sf "$ROOT/bin/repograph" "$BIN_DIR/repograph"
  TARGET="$BIN_DIR/repograph"
  say "linked $TARGET -> $ROOT/bin/repograph"
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "note: $BIN_DIR is not on your PATH. Add to your shell profile:"
     say "  export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

if [ "$DESKTOP" = "1" ]; then
  case "$(uname -s)" in
    Darwin)
      APPS="$HOME/Applications"
      mkdir -p "$APPS"
      if python3 "$ROOT/packaging/bundle.py" "$TARGET" -o "$APPS" --platform darwin >/dev/null 2>&1; then
        say "created $APPS/repograph.app — open it from Spotlight or the Finder"
      fi
      ;;
    Linux)
      APPS="$HOME/.local/share/applications"
      ICONS="$HOME/.local/share/icons"
      mkdir -p "$APPS" "$ICONS"
      if python3 "$ROOT/packaging/bundle.py" "$TARGET" -o "$APPS" --platform linux >/dev/null 2>&1; then
        mv -f "$APPS/repograph.svg" "$ICONS/repograph.svg" 2>/dev/null || true
        command -v update-desktop-database >/dev/null 2>&1 && \
          update-desktop-database "$APPS" >/dev/null 2>&1 || true
        say "created $APPS/repograph.desktop — it will appear in your application launcher"
      fi
      ;;
  esac
fi

echo
say "done. Try:"
say "  repograph scan /path/to/repo     scan from the terminal"
say "  repograph ui                     open the desktop UI"
