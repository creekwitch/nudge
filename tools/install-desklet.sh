#!/usr/bin/env bash
# Install the Nudge Cinnamon desklet for the current user.
# Usage: tools/install-desklet.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/cinnamon/desklets/nudge@creekwitch"

if ! command -v cinnamon >/dev/null 2>&1; then
    echo "cinnamon not found — this desklet is for Linux Mint's Cinnamon desktop." >&2
    echo "(the files can still be copied; they just need Cinnamon to run)" >&2
fi

mkdir -p "$DEST"
cp -f "$HERE"/desklet/nudge@creekwitch/{metadata.json,desklet.js,stylesheet.css,settings-schema.json} "$DEST/"

echo "installed to $DEST"
echo
echo "Now, on the desktop:"
echo "  1. Right-click the desktop → Add desklets"
echo "  2. Find 'Nudge' and click Add"
echo "  3. It reads the daemon at http://127.0.0.1:8130 by default —"
echo "     change the port under its settings (⚙) if you moved the UI."
echo
echo "The desklet needs the settings server running:  nudge ui"
