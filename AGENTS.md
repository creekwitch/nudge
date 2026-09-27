# AGENTS.md — Nudge

A care reminder daemon for Linux. By Haruka Tenou. Read `SPEC.md` for what it is and
`DEVPLAN.md` for how to build it. **This file is the law for any agent
touching the repo.**

## The constitution (from the design doc — never violate these)

1. **States, never asks.** A reminder says the thing exists. Never "did you
   do it?" — no surveillance-y phrasing, ever.
2. **No guilt.** No streaks, scores, statistics-as-guilt, no penalty of any
   kind. The log is for tuning, not display-as-judgment.
3. **"Didn't do it" is a first-class exit.** The Gear 3 popup has exactly
   three exits: Done / Didn't do it / Snooze. No plain dismiss/X. A "Didn't
   do it" is logged honestly and offered a kind line. This keeps "Done"
   truthful; that truth is the whole system's trust.
4. **Local only.** No network/cloud anything in the daemon. The two
   outbound integrations (Discord webhook, Hermes agent handoff) are the
   accountability layer and are explicitly configured; nothing else calls
   out.
5. **Quiet hours queue, never drop** — chores/nudges deferred during quiet
   hours are delivered when quiet hours end. Appointments break through at
   Gear 1 only (unless `hard: true`).
6. **One popup.** Multiple due reminders render as a queue in the single
   always-on-top window, never stacked windows.

## Repository layout

```
nudge/
  AGENTS.md            ← this file
  SPEC.md              ← what & why (stable north star)
  DEVPLAN.md           ← phased build plan (revised per phase)
  reminders.yaml       ← the user's reminders (data, not code — never
                        overwrite without reading current contents first)
  config.yaml          ← behavior settings
  nudge/
    __init__.py
    schedule.py        ← pure: parse schedules/quiet hours, compute due-ness
    gears.py           ← pure: given state + config, what gear applies now
    voice.py           ← pure: phrase pools, variation selection, no repeats
    state.py           ← pure: firing/ack ledger logic (what fired, when)
    models.py          ← dataclasses for Reminder, Config, Firing
    store.py           ← the ONLY module that reads/writes YAML files
    daemon.py          ← the loop: schedule → gears → actions (thin)
    actions.py         ← notify-send / paplay / popup spawn (subprocess I/O)
    popup.py           ← GTK always-on-top window (Gear 3)
    candle.py          ← Discord webhook (The Witness) + hearth report
    server.py          ← tiny localhost HTTP API for the settings UI
  ui/                  ← settings/control panel (local web UI)
  tests/               ← pytest, mirrors nudge/ module-for-module
  tools/               ← test-nudge.sh, install-service.sh, check scripts
  nudge.service        ← systemd user unit
```

## Conventions (house rules, applied here)

- **Pure logic in its own module with its own tests.** Everything that
  decides (is this due? which gear? which phrase? is it quiet hours?) lives
  in `schedule.py` / `gears.py` / `voice.py` / `state.py` as pure functions
  taking explicit `now`/state arguments. `daemon.py` and `actions.py` only
  wire decisions to the real clock and real subprocesses. If a rule is
  worth having, it is testable without sleeping, spawning, or notifying.
- **Inject the clock.** Every pure function takes `now: datetime`. Never
  call `datetime.now()` below `daemon.py`. This is what makes escalation
  and quiet-hour-crossing-midnight testable.
- **`store.py` is the only file I/O.** Modules that decide things never
  touch the disk. `store.py` reads reminders/config, and writes the firing
  ledger; it validates on load and refuses silently-incompatible files
  loudly (a config error is a notification, not a crash loop).
- **One definition of "due".** `schedule.next_fire(reminder, after)` is the
  only place recurrence math lives. The daemon, the settings UI's "next
  upcoming" card, and the status panel all ask it. A second derivation is
  a disagreement waiting to ship.
- **One definition of "quiet".** `schedule.is_quiet(hours, day, t)` handles
  midnight-crossing; nothing else answers that question.
- **Phrase pools never repeat consecutively.** `voice.pick(pool,
  last_used)` is the rule; check `tests/test_voice.py` for the
  wallpaper-effect regression.
- **All user-visible text goes through the voice register.** Warm, slightly
  witchy, affectionate. Never sarcastic, never corporate, never
  imperative-cold. New UI strings are copy in `voice.py` or the UI's own
  strings file — not hardcoded in markup scattered around.
- **`textContent`, never `innerHTML`** in the web UI. Reminder text is the
  user's own words.
- **Dates in the UI use local time, always.** No `toISOString()` for any
  user-facing date — it is wrong by a day outside UTC.
- **Additive config.** New config keys get defaults so existing files keep
  working. Never rename a key; never require a key that old files lack.

## Verification ladder (run ALL before claiming a daemon/UI change works)

```bash
cd ~/nudge
uv run pytest -q                    # pure logic + API tests (no sleeps, no real notifications)
make check-shell                    # bash -n on every tools/*.sh
nudge test-fire <id>                # drives ONE fake reminder through all gears
                                    # against the REAL session (notify-send, popup, chime)
./tools/check-popup.sh              # spawn popup headless-able probe; assert 3 exits, no X
```

Then **watch it on the real desktop**: `nudge test-fire` with gear delays
temporarily set to seconds in a scratch config. A unit suite passing says
nothing about whether `notify-send --urgency=critical` actually persists on
this session, or whether the GTK popup shows on all workspaces under
Wayland vs X11 — those are build-time checks recorded in `SPEC.md` §
Platform findings.

## Session protocol

- Read `DEVPLAN.md` → current phase → "Next Action". Do that one thing.
- Commit after each verified step, not at session end.
- Update `DEVPLAN.md` (phase status, Next Action) and `SESSION.md` before
  stopping. Never stop with "continue the daemon work" — name the file and
  the behavior.
- **Never write the user's real `reminders.yaml`** except through the app
  or with explicit direction; it is the user's memory, not a fixture. Tests use
  scratch dirs.
