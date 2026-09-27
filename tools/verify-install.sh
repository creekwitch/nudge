#!/usr/bin/env bash
# Fail loudly if the INSTALLED copy has drifted from this checkout.
#
# Why this exists: the running daemon / CLI / popup read the installed copy
# at ~/.local/share/nudge, never the checkout. An edit to source that is not
# followed by `make install` is invisible to the app — which made two bug
# fixes look broken on 2026-09-26. This turns that silent drift into a
# non-zero exit. Run it after `make install` (make install-all does).
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
LIB="${XDG_DATA_HOME:-$HOME/.local/share}/nudge"
DRIFT=0

if [ ! -d "$LIB/nudge" ]; then
    echo "FAIL: nothing installed at $LIB — run 'make install'"
    exit 1
fi

# compare every source .py against its installed twin
for f in "$SRC"/nudge/*.py; do
    base="$(basename "$f")"
    if ! cmp -s "$f" "$LIB/nudge/$base"; then
        echo "DRIFT: nudge/$base differs from installed copy"
        DRIFT=1
    fi
done
for f in "$SRC"/ui/*; do
    base="$(basename "$f")"
    if [ -f "$f" ] && ! cmp -s "$f" "$LIB/ui/$base"; then
        echo "DRIFT: ui/$base differs from installed copy"
        DRIFT=1
    fi
done

if [ "$DRIFT" -eq 1 ]; then
    echo
    echo "FAIL: installed copy is stale. The running app does NOT have your edits."
    echo "      Run: make install   (then restart: systemctl --user restart nudge.service)"
    exit 1
fi
echo "PASS: installed copy matches source (no drift)"
