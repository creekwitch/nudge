#!/usr/bin/env bash
# Bundle Nudge into a distributable zip: source, tests, docs, sounds, desklet.
# Excludes caches, scratch state, and anything generated.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$HOME/nudge-$(date +%Y%m%d).zip}"
STAGE="$(mktemp -d)"
NAME="nudge"

mkdir -p "$STAGE/$NAME"
# everything tracked by git — the archive is exactly what the repo carries
git -C "$HERE" archive --format=tar HEAD | tar -x -C "$STAGE/$NAME"

# egg-info is build cruft (a `pip install -e .` side effect), not source. It is
# tracked, so git archive brings it along — drop it so the archive is clean.
rm -rf "$STAGE/$NAME/nudge.egg-info"

# a note for whoever unpacks it
cat > "$STAGE/$NAME/UNPACK.txt" <<'TXT'
Nudge — a care reminder daemon
Haruka Tenou. Sept 2026.

A small desktop daemon that reminds you of appointments, chores and
responsibilities. It states that a thing exists. It never asks whether
you did it, never keeps score, never guilt-trips.

------------------------------------------------------------------
START HERE
------------------------------------------------------------------

Nudge targets Linux Mint with Cinnamon, on X11.

1. Install the two system packages it needs:

     sudo apt install python3-gi python3-yaml python3-gi-cairo

   (python3-gi needs the Cinnamon session already running for popups
   to appear on all workspaces.)

2. Run the tests. They should all pass before you trust it:

     cd nudge
     python3 -m pytest -q            # expect: 85 passed

3. Write down what you actually want to be reminded of:

     cp reminders.example.yaml ~/.config/nudge/reminders.yaml
     # ...then edit that file. It's plain YAML, comments explain
     # each reminder type.

   Or use the settings panel (step 5) — it edits the same file.

4. Put the daemon under systemd so it starts with your session:

     ./tools/install-service.sh
     systemctl --user enable --now nudge.service

   To check on it:   systemctl --user status nudge.service
   To stop it:       systemctl --user disable --now nudge.service

5. The control panel — this is where you shape everything:

     nudge ui

   ...then open http://127.0.0.1:8130

   Four tabs (Reminders / Quiet hours / Behavior / Status) and a
   calendar. You can drag appointments and chores onto other days
   to reschedule, and click any day for Done / Snooze /
   Didn't-do-it on each reminder.

   Leave this running if you want the calendar and desklet to work —
   it's a normal foreground program; Ctrl-C ends it.

6. Optional: a desktop desklet

     make install-desklet

   Then right-click the desktop -> Add desklets -> Nudge.
   It shows what's coming and needs `nudge ui` running.

------------------------------------------------------------------
NOT VERIFIED ON EVERY DESKTOP
------------------------------------------------------------------

The build machine ran EndeavourOS/MATE with no Cinnamon session, so
these parts are unproven in the exact environment you may be running:

  * The desklet. Its JavaScript parses and the server it talks to is
    fully tested, but it has not been rendered under GJS on Cinnamon.

  * desklet.js is written for libsoup 2.4 (Mint 20/21/22). On a Mint
    that has moved to libsoup 3 it needs the newer async form — the
    file says so in a comment.

  * Popups are pinned to the corner named in Behavior (default
    bottom-right) and told to appear on all workspaces.

If something is wrong, that's useful information, not a failure.
Please open an issue and say what you saw.

------------------------------------------------------------------
WHAT IT WILL AND WON'T DO
------------------------------------------------------------------

It never sends anything over the network. Reminders are a plain YAML
file you can read and edit (and copy to another machine). The
settings server listens only on 127.0.0.1.

It does not track, score, streak or nag. There are exactly three ways
out of a popup: Done, Didn't-do-it, and Snooze. "Didn't do it" is
logged and rescheduled with no penalty attached — it exists so that
the honest answer is always available.

During your quiet hours, chores and nudges wait and are delivered
when quiet ends. Appointments still come through, quietly, unless a
reminder is marked hard: true.

README.md is the full picture. SPEC.md section 6 records what was
verified on a real session. AGENTS.md is the working agreement for
anyone editing the code.
TXT

( cd "$STAGE" && zip -qr "$OUT" "$NAME" )
rm -rf "$STAGE"
echo "wrote $OUT"
unzip -l "$OUT" | tail -3
