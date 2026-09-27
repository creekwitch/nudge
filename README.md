# Nudge 🕯️

A care reminder daemon for Linux.

By Haruka Tenou — <https://github.com/creekwitch/nudge>.

Nudge states the thing exists. It never asks "did you do it?", never
keeps score, and never offers a way out that isn't honest: the popup's
only exits are **Done**, **Didn't do it** (logged kindly, no penalty),
and **Snooze**. Quiet hours queue chores and nudges instead of dropping
them; appointments still ping once unless marked `hard`.

## Install

```bash
git clone https://github.com/creekwitch/nudge.git
cd nudge
sudo apt install python3-gi python3-yaml python3-gi-cairo
make install          # runs tests, installs the systemd user service
```

`make install` runs the test suite first, so it needs pytest:

```bash
python3 -m pip install --user pytest     # or: pipx install pytest
```

If you would rather skip the pre-flight check, run
`tools/install-service.sh` directly — it installs without running the suite.
With [uv](https://docs.astral.sh/uv/) installed, `uv run pytest -q` works with
no setup at all.

Config lives in `~/.config/nudge/` (`reminders.yaml`, `config.yaml`);
state in `~/.local/state/nudge/` (ledger, log, popup handshake).

## Use

```bash
nudge status            # what's pending, deferred, next
nudge add <id> <type> <text> …   # appointment | chore | nudge
nudge ui                # settings panel + calendar at http://127.0.0.1:8130
nudge log --lines 40    # firings + verdicts, for tuning
nudge test-fire <id>    # walk one reminder through all three gears
tools/check-popup.sh    # popup self-check on the real session
make install-desklet    # Cinnamon desktop widget (Mint)
```

### The settings panel

Four tabs (Reminders / Quiet hours / Behavior / Status) plus a **📅
calendar modal** — a month grid of every scheduled fire, colour-coded by
type (appointments pink, chores teal, nudges peach), past events dimmed,
today outlined. `GET /api/calendar?year=&month=` feeds it from
`schedule.occurrences_in_month()`; the browser derives no dates of its own.
An interval nudge collapses to one entry per day so a 90-minute reminder
cannot flood the month.

The panel wears the house design language: one `--wall` on `body` and
every panel sampling it through the glass tokens, a sliding ink pill under
the active tab, a gradient wordmark, and a coloured rail down each card
naming its type.

### The Cinnamon desklet

`desklet/nudge@creekwitch/` is a plain-JS Cinnamon desklet: it shows what
Nudge is waiting on (the highest-gear reminder, with a ●●● escalation
dot), the next scheduled thing, and anything parked through quiet hours —
and it takes verdicts (Done / Didn't do it / Snooze 10) straight from the
desktop via `POST /api/popup-verdict`. Install with
`make install-desklet`, then right-click the desktop → Add desklets →
Nudge. It needs `nudge ui` running (it reads the same localhost API).

### Add-by-chat (the lowest-friction path): tell your agent the reminder in
conversation; he runs `nudge add` for you. The UI is for editing; chat
is for capture.

### Types

| type | fields | example |
|---|---|---|
| appointment | `when`, optional `hard` | dentist, Oct 3, 2pm |
| chore | `schedule: "mon,wed,fri 13:00"` | laundry |
| nudge | `every: 90m`, optional `active_only` | stretch |

### Gears

1. Normal notification, warm varied phrasing.
2. +N minutes unacknowledged (default 10): critical notification + chime.
3. +M more (default 10): persistent always-on-top popup — Done /
   Didn't do it / Snooze (5/10/30/60). One popup, whole queue inside.

### Accountability (all opt-in, v1 complete)

- **The Witness** — every Done lights a candle: one line to Discord
  (`witness.webhook_url`). No commentary, no score.
- **The Evening Telling** — at `telling.hour`, the day's Dones are told
  back via the Hermes hook and optionally Discord.
- **The Pair Nudge** — per-reminder `pair: <person>`; a Discord ping to
  one person you name, only for the reminders where you turned it on.

## Repository rules

Agents: read `AGENTS.md` before touching anything. The constitution
(states, never asks · no guilt · three exits · local only · queue don't
drop · one popup) is not optional. Pure logic takes an injected clock;
`store.py` is the only file I/O; run `python3 -m pytest -q` plus the
real-desktop checks before claiming anything works.

## License

**Freeware** — free to use, read, modify, and share. Not for sale: no
selling, no fees, no bundling into paid products, no monetizing. Sharing
is welcome, with a link back. See [LICENSE](LICENSE).

Nudge is a reminder tool, not a medical device or a safety system — do not
rely on it where a missed notice could cause harm.

---

## Companions

Other small, local-only tools from the same hand:

- **[The Garden](https://github.com/creekwitch/the-garden)** — a private,
  local-only desktop diary. One HTML file, a stdlib-only Python server, and
  a GTK window; your writing never leaves the machine. Freeware.
