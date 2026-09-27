# Nudge — SPEC

*Design notes (Sept 2026).
This document is the stable north star; DEVPLAN.md carries the phases.*

## 1. Problem

Many people are time-blind and hyperfocus-prone: absorbed in a task, they
lose the shape of the day around them. Conventional reminder apps fail them
two ways: they dismiss on click (forgotten instantly) or nag with guilt.
Nudge does neither. It states facts about time kindly and persistently —
never a manager that grades you.

## 2. Personas & tone contract

- Reminder voice: warm, slightly witchy, affectionate. Varies every
  firing; never repeats the previous phrase. Weaves in the optional
  `note` field as personal context.
- Prohibited: sarcasm, "did you…?", corporate neutrality, streaks/scores,
  penalty of any kind, dismiss-without-accounting.
- "Didn't do it" gets a kind line ("It'll wait. It's not going
  anywhere.") and an honest reschedule.

## 3. Domain model

### Reminder (one YAML entry, `~/.config/nudge/reminders.yaml`)

| Field | Types | Notes |
|---|---|---|
| `id` | str, required | unique, slug |
| `type` | `appointment` \| `chore` \| `nudge` | drives schedule + quiet-hour behavior |
| `when` | datetime | appointment only, local time |
| `schedule` | `"mon,wed,fri 13:00"` | chore only |
| `every` | `"90m"`, `"2h"` … | nudge only |
| `active_only` | bool | nudge only; fires only while user has recent input activity |
| `text` | str, required | the subject; voice wraps it |
| `note` | str | personal context the voice may weave in |
| `hard` | bool | appointment: full gears even in quiet hours |
| `pair` | str | optional person (Discord ping after all gears unhandled) |
| `gear2_min` / `gear3_min` | int | per-reminder escalation overrides (default from config) |

### Config (`~/.config/nudge/config.yaml`)

- `gear2_delay_min: 10`, `gear3_delay_min: 10`
- `snooze_options: [5, 10, 30, 60]`
- `chime: true`, `chime_repeat_s: 60`
- `popup_corner: bottom-right`
- `quiet_hours`: per-day `[start, end]`, may cross midnight; default
  23:30–09:00 all days
- `witness`: `{enabled, webhook_url, channel_label}` — The Witness
- `telling`: `{enabled, hour: 20}` — Evening Telling delivery
- `hermes`: `{enabled, hook_path}` — how the running Hermes agent receives
  the hearth report

### Firing state (ledger, `~/.local/state/nudge/ledger.json`)

Per reminder: last fired time, current gear, last phrase used, snoozed
until (or null), acknowledged verdict (`done`/`didnt`/snooze), timestamps.
Derived fresh on each daemon tick; the ledger is facts, not logic.

## 4. Behavior

### Gears (pure logic in `gears.py`)

- **Gear 1**: `notify-send` normal urgency, varied phrasing.
- **Gear 2** (`+N` unacked): `--urgency=critical --expire-time=0` + chime.
- **Gear 3** (`+M` more): persistent always-on-top frameless popup,
  skip-taskbar, on-all-desktops, pinned to configured corner. Exactly
  three exits. Optional 60s soft chime while open. One popup total; a
  queue/list inside it when multiple reminders are due.
- Appointments in quiet hours: Gear 1 only unless `hard: true`.
- Chores/nudges in quiet hours: silently deferred, delivered at
  quiet-hours end (queued, never dropped).

### Recurrence

- Chore done → next occurrence per schedule. Chore "didn't do it" → next
  occurrence too (honest, no penalty). Appointment "didn't do it" is not
  offered — Snooze only. Nudge done → next interval (or same interval if
  `active_only` and still active).

### Accountability layer (all four in v1)

1. **The Witness** — every Done → one line to local log + Discord webhook
   (chores channel). No commentary.
2. **The Evening Telling** — at `telling.hour`, compile the day's Dones
   into a hearth report; deliver via Hermes hook and optionally Discord.
3. **The Honest Confession Button** — the three-exit popup itself.
4. **The Pair Nudge** — per-reminder `pair:` flag; after all gears
   unhandled → Discord ping to that person. Opt-in per reminder only.

## 5. Interfaces

- **CLI**: `nudge start|status|test-fire <id>|list|add …` (add-by-chat
  convention: the agent appends to `reminders.yaml` or calls `nudge add`).
- **HTTP API** (`server.py`, localhost only, for the settings UI):
  - `GET /api/reminders`, `POST /api/reminders`, `PATCH/DELETE /api/reminders/{id}`
  - `GET/PUT /api/config` (quiet hours, gears, behavior)
  - `GET /api/status` (pending / deferred / next upcoming)
  - `POST /api/test-fire` `{id}` — drives a fake reminder through all gears
- **Settings UI** (local web page served by `server.py`, no build step,
  vanilla JS): Reminders tab (form adapts to type), Quiet hours (per-day
  dual-range editor, today highlighted, copy-to-all), Behavior (gears,
  chime, corner, hard toggle), Status (pending/deferred/next + test-fire
  button).

## 6. Platform findings (Phase 0 spike — verified 2026-09-26; the spike ran on
an EndeavourOS/MATE box. **Primary target: Linux Mint, Cinnamon desktop** —
Mint 21/22 is X11, so the findings below carry over; items marked ⚠ need a
one-time re-check on your machine at install.)

- **Session**: **X11** on both spike box (MATE) and target (Cinnamon).
  No Wayland layer-shell path needed for v1; `gtk-layer-shell` is installed
  anyway (0.10.1) if a future port needs it.
- **Python**: spike box needed `/usr/bin/python3` for GI. Mint's system
  python3 (3.10 on Mint 21 / 3.12 on Mint 22) ships `python3-gi` and
  `python3-yaml` via apt — install line for her machine:
  `sudo apt install python3-gi python3-yaml python3-gi-cairo`. Same rule:
  daemon runs on system python. **No croniter** — hand-roll the schedule
  parser (already the plan).
- **Popup strategy**: plain GTK3 `Window(type=POPUP)` + `set_keep_above`,
  `stick()` (all workspaces), `set_skip_taskbar_hint`/`set_skip_pager_hint`,
  `type_hint=DOCK`, manual corner `move()` — window created successfully on
  this session, frameless (POPUP type has no WM decorations, so no close X
  by construction). Corner pin via `Gdk.Display.get_primary_monitor()`
  geometry + margin. `spikes/popup.py` is the reference implementation.
- **Critical notification persistence**: `notify-send -u critical -t 0`
  accepts and sends on the spike box (MATE). ⚠ Cinnamon ships its own
  notification daemon (`cinnamon-settings notifications`); verify the
  critical bubble persists until dismissed on her machine during the
  Phase 2 real-desktop pass.
- **Idle time (`active_only`)**: no `xprintidle` installed and no
  passwordless sudo, **but** the XScreenSaver extension query works via
  ctypes against `libXss` (verified: returned real idle ms with zero
  dependencies beyond libX11/libXss, which are already installed). `idle_ms`
  helper goes in `actions.py` with that exact ctypes incantation (set
  restype/argtypes on XOpenDisplay, XDefaultRootWindow and
  XScreenSaverQueryInfo *before* calling — the order caused a segfault once).

## 7. Risks

| Risk | Mitigation |
|---|---|
| Popup can't stay on top under Wayland without layer-shell | Phase 0 spike; fallback = critical notification with actions (fewer guarantees, documented) |
| Daemon crash silently kills reminders | systemd user service with `Restart=on-failure`; watchdog notification on start |
| Ledger/config corruption | writes are atomic (tmp + rename); load errors surface as a notification |
| Voice pools feel stale | pools sized ≥6 phrases per context; log phrase usage so tuning can see repetition |
| Discord webhook secret | lives in config file with 0600 perms, never logged |

## 8. Out of scope (v1)

Streaks, scores, stat displays, "did you do it" follow-ups, network/cloud
anything beyond the two explicit accountability hooks, mobile, multi-user.

## 9. Acceptance criteria (v1)

1. Appointment fires at its time with warm varied phrasing; escalates to
   critical then popup with three exits; Done lights a candle (log +
   Discord line); appointment offers no "didn't do it".
2. Chore fires on its weekdays; survives quiet hours by deferring;
   delivery lands within one tick of quiet-hours end.
3. Nudge respects `active_only` (or documented fallback) and its interval.
4. Snooze menu with the four options reschedules correctly and logs.
5. `nudge test-fire` drives all three gears in seconds with scratch config.
6. Settings UI edits reminders/quiet-hours/config through the API and the
   daemon picks changes up without restart.
7. Evening Telling compiles the day's Dones and delivers via both channels
   when enabled.
8. Full pytest suite green; popup verified on the real session; systemd
   user service survives relogin.
