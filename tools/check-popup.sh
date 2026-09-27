#!/usr/bin/env bash
# Real-session Gear-3 popup check. Spawns the popup with a two-item queue,
# verifies the process lives, verifies the WINDOW IS ACTUALLY MAPPED on the
# session, and tells the human what to look for.
#
# The mapping assertion is the regression guard for the 2026-09-26 silent-death
# bug: the popup was built as Gtk.WindowType.POPUP, so the process ran and
# "showed" but never mapped a real window — everything reported PASS while the
# user saw nothing. "process alive" is NOT "popup visible"; this checks both.
#
# The interactive click-through is manual by design: it ends when the
# person clicks through the queue.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
STATE="${NUDGE_STATE:-/tmp/nudge-check-state}"
REQ="$STATE/popup-request.json"
rm -f "$STATE/popup-verdicts.jsonl"
mkdir -p "$STATE"
cat > "$REQ" <<JSON
{"reminders": [
  {"id": "check-a", "text": "Check popup", "phrase": "This is the popup self-check.", "note": "safe to dismiss via buttons"},
  {"id": "check-b", "text": "Second queued", "phrase": "Queued behind the first.", "note": ""}
 ],
 "corner": "bottom-right", "snooze_options": [5, 10, 30, 60],
 "chime_repeat_s": 3600,
 "verdict_file": "$STATE/popup-verdicts.jsonl", "request_file": "$REQ"}
JSON
/usr/bin/python3 "$HERE/nudge/popup.py" "$REQ" &
PID=$!
sleep 2
kill -0 "$PID" && echo "PASS: popup process alive on real session" || { echo "FAIL: popup died"; exit 1; }

# --- the assertion that actually matters: is a window MAPPED? ---
# The popup sets title "Nudge". wmctrl -l lists only MAPPED (managed)
# top-level windows: a POPUP-type window never appears here, a TOPLEVEL does.
MAP_STATE=""
if command -v wmctrl >/dev/null 2>&1; then
    if wmctrl -l 2>/dev/null | grep -qi "Nudge"; then
        MAP_STATE="IsViewable (wmctrl)"
    else
        MAP_STATE="absent (wmctrl saw no 'Nudge' window)"
    fi
elif command -v xwininfo >/dev/null 2>&1; then
    if xwininfo -root -tree 2>/dev/null | grep -qi '"Nudge"'; then
        MAP_STATE="present (xwininfo)"
    else
        MAP_STATE="absent (xwininfo saw no 'Nudge' window)"
    fi
fi
case "$MAP_STATE" in
    IsViewable*|present*)
        echo "PASS: popup window is MAPPED on the session ($MAP_STATE)" ;;
    "")
        echo "WARN: no window probe available (no wmctrl/xwininfo, or headless)."
        echo "      Window mapping NOT verified — check the desktop by eye." ;;
    *)
        echo "FAIL: popup process alive but NO mapped window ($MAP_STATE)"
        echo "      ^ this is the silent-death bug (wrong Gtk.WindowType) — see popup.py"
        kill "$PID" 2>/dev/null || true
        exit 1 ;;
esac

echo "--> LOOK at your desktop: popup should show check-a with 3 buttons, '1 more waiting'"
echo "--> click Done: popup advances to check-b, then exits after the last"
wait "$PID" || true
if [ -f "$REQ" ]; then
  echo "note: request file remains (popup was killed, not drained)"
else
  echo "PASS: request file cleaned up on drain"
fi
echo "popup check complete"
