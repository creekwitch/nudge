# Nudge — DEVPLAN

*Revised per phase. Status: **ALL PHASES COMPLETE + hardened** (v1,
2026-09-26) — 59 tests green; live-verified on desktop: notifications,
Gear-3 popup (visually), settings UI (browser CRUD), chime (played),
autonomous e2e run, popup replacement (old killed, new owns the queue).
Late catches worth remembering: the popup must spawn on
**/usr/bin/python3** (a venv python lacks `gi` — silent death); the
Evening Telling had to be *wired into the tick* (a tested delivery
function nobody calls ships nothing); and the server must never write
the ledger (the daemon process owns it — /api/test-fire now only
re-reads it). Remaining for a real install: ⚠ re-checks in SPEC §6 on
a Mint box, real webhook/telling config, and the acceptance week
(tune gear delays + phrase pools from the log via `nudge log`).*

Post-v1 polish (2026-09-26): the `nudge` CLI never actually existed on
PATH — `[project.scripts]` was inert (unpackaged project). Fixed twice
over: pyproject now packages the project (`tool.uv.package = true` +
setuptools build-system, so `uv run nudge` works in the checkout), and
install-service.sh writes a thin `~/.local/bin/nudge` launcher running
the installed copy on system python (so `make install` gives her the
real command). Also: `nudge list` on an empty reminders file printed
nothing — now a warm LIST_EMPTY voice pool line. Installer exercised
for real; daemon running as user service; check-popup.sh passed.

Bug round (2026-09-26, three reports) — **all three were the same
meta-bug wearing different faces: the running app reads the INSTALLED copy
at `~/.local/share/nudge`, never the checkout, and edits to source had not
been installed.**
1. `bad weekdays in schedule: 'Friday'` — the settings form is free text but
   `parse_schedule` only accepted 3-letter lowercase days, *and* split days
   from time on the FIRST space (so `"Monday, Wednesday 13:00"` also broke).
   Now: time is the last whitespace token; a day token is valid if it is a
   prefix (3+ chars) of the full English day name. `Friday`/`FRI`/`fri` work;
   `Fridays`/`fribble` still bounce. 3 regression tests in test_core.py.
2. Desklet froze and took no clicks — `this._meta` is **reserved by Cinnamon's
   Desklet base class** (it holds the metadata object), so our St.Label was
   clobbered and `this._meta.set_text()` threw `TypeError: set_text is not a
   function`, killing the refresh handler. Renamed to `this._metaLine`.
3. **No popup ever appeared** — the popup was built as `Gtk.WindowType.POPUP`
   (a menu-type override-redirect window GTK never maps as a real top-level)
   with a `DOCK` hint stacked on top. The process ran, "showed", and stayed
   invisible: `check-popup.sh` said PASS the whole time because it only tested
   *process alive*. Now `TOPLEVEL` + `set_decorated(False)` + `UTILITY` hint +
   a `set_title("Nudge")` so the window is findable.

Hardening from the round: `tools/verify-install.sh` fails loudly when the
installed copy drifts from source; `make install-all` installs code+desklet
then verifies; `tools/check-popup.sh` now asserts the window is actually
MAPPED (verified to FAIL on the buggy type and PASS on the fix — a real
regression guard, not a rubber stamp). 80 tests green.

⚠ Not addressed (awaiting a decision): Cinnamon has
`org.cinnamon.desktop.notifications display-notifications=false` on this box,
so gear-1/gear-2 `notify-send` banners render silently in the tray. The
popup is unaffected (it is its own window), but the gentle early gears are
effectively invisible unless that setting is flipped.


## Phase 0 — Platform spike (1 session, ≤3 files)

Goal: answer SPEC §6 before any daemon code.

1. Detect session: `echo $XDG_SESSION_TYPE`; check `gtk-layer-shell` availability.
2. Prototype the always-on-top popup two ways (plain GTK hints; layer-shell
   if present). Verify: on top, on all workspaces, no taskbar entry, no
   close X. Record which works.
3. Verify `notify-send --urgency=critical --expire-time=0` persistence.
4. Probe idle-time source for `active_only`.
5. Write findings into SPEC §6. Commit.

**Exit:** SPEC §6 has real answers; a `spikes/popup.py` prototype demonstrably
pinned to a corner across workspaces.

## Phase 1 — Skeleton + pure core (2 sessions, 5–8 files)

Files: `nudge/models.py`, `schedule.py`, `gears.py`, `voice.py`,
`state.py`, `store.py`, `tests/test_{schedule,gears,voice,state}.py`,
`reminders.yaml` (example), `config.yaml` (defaults), `pyproject.toml`,
`Makefile`.

- Models: dataclasses with `from_yaml_dict`/`to_yaml_dict`.
- `schedule.py`: `parse_schedule("mon,wed,fri 13:00")`, `parse_every("90m")`,
  `next_fire(reminder, after, now)`, `is_quiet(hours, now)` (midnight
  crossing!), `quiet_end(hours, now)` (for deferred delivery).
- `gears.py`: `gear_for(firing, now, config)` — pure escalation state
  machine; `in_quiet_appt_cap` logic.
- `voice.py`: phrase pools (≥6 per context: fire/gear2/gear3/done/didnt),
  `pick(pool, last_used)`, `render(reminder, pool)` weaving `note`.
- `state.py`: ledger ops — `register_fire`, `acknowledge`, `snooze`,
  `deferred queue` helpers. Pure over a dict.
- `store.py`: atomic YAML read/write, validation, ledger persistence.

**Exit:** `uv run pytest -q` green, including: midnight-crossing quiet
hours, chore crossing a week boundary, phrase never repeats consecutively,
gear escalation with injected `now`, deferred queue drains at quiet end.

## Phase 2 — Daemon + actions (2 sessions, 4–6 files)

Files: `daemon.py`, `actions.py`, `cli.py` (`nudge` entrypoint),
`tests/test_daemon.py` (actions monkeypatched to a recorder),
`nudge.service`, `tools/install-service.sh`.

- Loop: tick 30s (config override for tests), each tick: load state →
  compute due/gear transitions → dispatch actions → persist ledger.
- `actions.py`: `notify(urgency, text)`, `chime()`, `spawn_popup(queue)`
  — all thin subprocess/DBus wrappers behind a small interface so tests
  record instead of spawn.
- Deferral: quiet-hours queue drains on first non-quiet tick.
- Snooze handling: ledger `snoozed_until`; re-enters gear pipeline at
  Gear 1 (config: `snooze_reenters_at_gear: 1`).
- systemd user unit: `Restart=on-failure`, `WantedBy=default.target`.
- CLI: `nudge start|status|list|test-fire <id>|add`.

**Exit:** daemon runs under systemd, survives relogin; `nudge test-fire`
walks a fake reminder through gears 1→2→3 in seconds with scratch config
(seconds-scale delays); real notifications + popup observed on the desktop.

## Phase 3 — Gear 3 popup (1–2 sessions, 2–4 files)

Files: `popup.py`, `tools/check-popup.sh`, `tests/test_popup_logic.py`.

- GTK window per Phase 0 finding (layer-shell or X11 hints). Frameless,
  always-on-top, all-workspaces, skip-taskbar, corner pinning.
- Queue rendering: one reminder focused, count of others, "next" cycling.
- Three exits only: Done / Didn't do it / Snooze(5/10/30/60). No X, no
  Escape-close (Escape opens Snooze menu instead — deliberate).
- Chime every 60s while open (config-gated).
- Result written back to ledger via a tiny unix socket or file handshake
  (popup is a separate process; daemon owns the ledger).

**Exit:** `tools/check-popup.sh` passes on the real session; the three
verdicts land in the ledger; Done candle appears in the log.

## Phase 4 — Accountability layer (1–2 sessions, 3–4 files)

Files: `candle.py`, `tests/test_candle.py`, config keys.

- Witness: Done → local candle log line + Discord webhook POST (urllib,
  no deps; 0600 perms on config; secret never logged; failures retried
  next tick, never dropped silently — a failed candle is queued).
- Pair Nudge: all gears expired unhandled + `pair:` set → Discord ping.
- Evening Telling: at `telling.hour`, compile day's Dones → hearth report
  → Hermes hook + optional Discord.
- Kind-line copy in `voice.py` pools (done/didnt/pair/telling registers).

**Exit:** candles observable in Discord channel + local log; telling fires
once per day; webhook failure leaves a queued candle, not a lost one.

## Phase 5 — Settings UI + server (2 sessions, 4–6 files)

Files: `server.py`, `ui/index.html`, `ui/app.js`, `ui/app.css`,
`tests/test_server.py`.

- localhost HTTP API per SPEC §5; daemon reads config/reminders fresh each
  tick (or on SIGHUP) so UI edits need no restart.
- UI: four sections per SPEC; form adapts to reminder type; quiet-hours
  dual-range editor with today highlight + copy-to-all; test-fire button
  wired to `/api/test-fire`; status view reads `/api/status`.
- Vanilla JS, no build step, `textContent` everywhere, Catppuccin Mocha
  tokens in CSS section 1 (house style).

**Exit:** all edits round-trip through the API and take effect in the
daemon within one tick; UI verified in a real browser at desktop size
(screenshot + DOM assertions); pytest server tests green.

## Phase 6 — Hardening + her acceptance week (1 session + calendar time)

- Log review tooling: `nudge log` shows firings/verdicts for tuning.
- Tuning pass after a week of real use: gear delays, phrase pools.
- `README.md`: install, and the add-by-chat convention.
- Full acceptance checklist (SPEC §9) walked on the real desktop.

## Dependency graph

```
P0 → P1 → P2 → P3 → P4 → P5 → P6
        └───────────┴── P4 can start after P2 (uses ledger + actions only)
```

## SESSION.md log

- 2026-09-26 — **Bug round.** Three reports: chore schedule rejected
  "Friday"; desklet unresponsive; no popup. Root cause for the confusion: all
  edits were made in the checkout while the app runs the installed copy.
  Fixed `parse_schedule` (full/cased day names, time-as-last-token),
  `desklet.js` (`_meta`→`_metaLine`, a Cinnamon base-class collision), and
  `popup.py` (`WindowType.POPUP`→`TOPLEVEL` — the invisible-popup bug);
  added `tools/verify-install.sh` drift guard, `make install-all`, 3 schedule
  regression tests, and a real window-mapped assertion in check-popup.sh.
  Next Action: flip `display-notifications` (pending a decision on) so gear-1
  banners show, then the acceptance week.
