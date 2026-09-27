"""The daemon loop: thin wiring of pure decisions to real side effects.

Reads reminders/config fresh every tick so UI edits need no restart.
"""
from __future__ import annotations

import time as time_mod
from datetime import datetime
from pathlib import Path

from . import actions, gears, schedule, state as state_mod, store, voice
from .models import APPOINTMENT, CHORE, NUDGE, Config, Reminder


class Daemon:
    def __init__(self, base_dir: Path | None = None, state_dir: Path | None = None):
        self.base = base_dir or store.DEFAULT_DIR
        self.state_dir = state_dir or store.DEFAULT_STATE_DIR
        self.ledger = store.load_ledger(store.ledger_path(self.state_dir))
        self.candles: list[str] = []       # queued witness lines (webhook may be down)
        self.last_told: str | None = None  # date of the last Evening Telling
        self.popup_pid = None

    # ---- paths

    def _reminders(self):
        return store.load_reminders(store.reminders_path(self.base))

    def _config(self) -> Config:
        return store.load_config(store.config_path(self.base))

    def _save_ledger(self):
        store.save_ledger(self.ledger, store.ledger_path(self.state_dir))

    def _log(self, line: str, now: datetime):
        store.append_log(self.state_dir / "log", line, now.strftime("%Y-%m-%d %H:%M"))

    # ---- the tick

    def tick(self, now: datetime) -> list[str]:
        """One scheduler pass. Returns human-readable actions taken (tests)."""
        cfg = self._config()
        reminders = self._reminders()
        taken: list[str] = []
        quiet = schedule.is_quiet(cfg.quiet_hours, now)

        taken += self._apply_verdicts(now, cfg)
        for r in reminders:
            e = state_mod.entry(self.ledger, r.id)
            taken += self._handle(r, e, now, cfg, quiet)

        taken += self._drain_deferred(reminders, now, cfg, quiet)
        taken += self._escalate(reminders, now, cfg, quiet)
        taken += self._witness(cfg, now)
        taken += self._telling(cfg, now)
        self._save_ledger()
        return taken

    def _apply_verdicts(self, now: datetime, cfg: Config) -> list[str]:
        """Consume popup verdicts from the file handshake."""
        taken = []
        for v in actions.poll_verdicts(self.state_dir):
            rid = v.get("id")
            if not rid:
                continue
            if v["verdict"] == "snooze":
                self.snooze(rid, int(v.get("snooze_min") or 10), now)
                taken.append(f"popup snooze {rid} {v.get('snooze_min')}m")
            elif v["verdict"] in ("done", "didnt"):
                self.acknowledge(rid, v["verdict"], now, cfg)
                taken.append(f"popup {v['verdict']} {rid}")
        return taken

    def _handle(self, r: Reminder, e: dict, now: datetime, cfg: Config,
                quiet: bool) -> list[str]:
        taken = []
        snoozed = state_mod.parse_ts(e["snoozed_until"])
        fired_at = state_mod.parse_ts(e["last_fired"])
        last_fired_for_sched = fired_at if e["gear"] else state_mod.parse_ts(e["verdict_at"])

        if e["deferred"]:
            return taken  # handled by _drain_deferred

        if not schedule.is_due(r, now, last_fired_for_sched, snoozed, fired_at):
            return taken

        if quiet:
            if r.type == APPOINTMENT:
                pass  # appointments break through (gear cap enforced below)
            else:
                self.ledger = state_mod.defer(self.ledger, r.id, now)
                taken.append(f"defer {r.id} (quiet hours)")
                return taken

        if r.type == NUDGE and r.active_only:
            idle = actions.idle_ms()
            if idle is not None and idle > 300_000:  # idle > 5 min: user away
                return taken

        phrase = voice.render(voice.FIRE, r.text, r.note, e["last_phrase"])
        actions.notify("Nudge", phrase)
        self.ledger = state_mod.register_fire(self.ledger, r.id, now, phrase)
        self._log(f"FIRE {r.id}: {phrase}", now)
        taken.append(f"fire {r.id} (gear 1)")
        return taken

    def _drain_deferred(self, reminders, now, cfg, quiet) -> list[str]:
        taken = []
        if quiet:
            return taken
        for r in reminders:
            e = state_mod.entry(self.ledger, r.id)
            if not e["deferred"]:
                continue
            phrase = voice.render(voice.FIRE, r.text, r.note, e["last_phrase"])
            actions.notify("Nudge", phrase)
            self.ledger = state_mod.register_fire(self.ledger, r.id, now, phrase)
            self._log(f"FIRE {r.id} (deferred from quiet hours): {phrase}", now)
            taken.append(f"deliver deferred {r.id}")
        return taken

    def _escalate(self, reminders, now, cfg, quiet) -> list[str]:
        taken = []
        for r in reminders:
            e = state_mod.entry(self.ledger, r.id)
            fired_at = state_mod.parse_ts(e["last_fired"])
            if fired_at is None or e["verdict"] or e["deferred"]:
                continue
            if e["snoozed_until"] and now < state_mod.parse_ts(e["snoozed_until"]):
                continue
            gs = gears.gear_for(r, fired_at, now, cfg, state_mod.parse_ts(e["snoozed_until"]))
            cap = gears.quiet_cap(r, cfg) if quiet else gears.GEAR3
            gear = min(gs.gear, cap)
            if gear != e["gear"]:
                self.ledger = state_mod.set_gear(self.ledger, r.id, gear, now)
                if gear == gears.GEAR2:
                    phrase = voice.render(voice.FIRE2, r.text, r.note, e["last_phrase"])
                    actions.notify("Nudge", phrase, critical=True)
                    actions.chime(cfg.chime_volume)
                    e = state_mod.entry(self.ledger, r.id)
                    self.ledger = state_mod.set_gear(self.ledger, r.id, gear, now)
                    self._log(f"GEAR2 {r.id}: {phrase}", now)
                    taken.append(f"escalate {r.id} -> gear 2")
                elif gear == gears.GEAR3:
                    queue = []
                    for r2 in reminders:
                        e2 = state_mod.entry(self.ledger, r2.id)
                        f2 = state_mod.parse_ts(e2["last_fired"])
                        if f2 is None or e2["verdict"] or e2["deferred"]:
                            continue
                        if e2["snoozed_until"] and now < state_mod.parse_ts(e2["snoozed_until"]):
                            continue
                        g2s = gears.gear_for(r2, f2, now, cfg,
                                             state_mod.parse_ts(e2["snoozed_until"]))
                        if min(g2s.gear, cap) >= gears.GEAR3:
                            queue.append({"id": r2.id, "text": r2.text,
                                          "phrase": e2["last_phrase"] or r2.text,
                                          "note": r2.note})
                    actions.spawn_popup(queue, cfg)
                    if cfg.chime:
                        actions.chime(cfg.chime_volume)
                    self._log(f"GEAR3 {r.id}: popup", now)
                    taken.append(f"escalate {r.id} -> gear 3 (popup)")
            # Pair Nudge: survived all gears, unhandled, opted in
            if (gears.pair_ready(r, fired_at, now, cfg)
                    and not state_mod.parse_ts(e["pair_sent"])):
                from .candle import send_pair_ping
                send_pair_ping(cfg, r)
                self.ledger = state_mod.mark_pair_sent(self.ledger, r.id, now)
                self._log(f"PAIR {r.id} -> {r.pair}", now)
                taken.append(f"pair ping {r.id} -> {r.pair}")
        return taken

    def _witness(self, cfg: Config, now) -> list[str]:
        from .candle import drain_candles
        drain_candles(cfg, self.candles)
        return []

    def _telling(self, cfg: Config, now: datetime) -> list[str]:
        """The Evening Telling: once per day, at cfg.telling_hour, compile
        the day's Dones and deliver them. Gated on a last-told date so a
        long-running daemon tells exactly once."""
        from .candle import hearth_report, deliver_telling
        if not (cfg.telling_enabled and now.hour == cfg.telling_hour):
            return []
        today = now.date().isoformat()
        if self.last_told == today:
            return []
        dones = [line for line in self._todays_dones(now)]
        report = hearth_report(dones, now.date())
        delivered = deliver_telling(cfg, report)
        self.last_told = today
        self._log(f"TELLING ({','.join(delivered) or 'undelivered'}): day with "
                  f"{len(dones)} dones", now)
        return [f"telling delivered via {','.join(delivered)}" if delivered
                else "telling compiled (no delivery channel enabled)"]

    def _todays_dones(self, now: datetime):
        """Today's DONE lines from the log, as candle-worthy entries."""
        path = self.state_dir / "log"
        prefix = now.strftime("%Y-%m-%d") + " DONE "
        if not path.exists():
            return []
        out = []
        for line in path.read_text().splitlines():
            if line.startswith(prefix):
                out.append(line[len(prefix):].strip())
        return out

    # ---- verdicts (called by the popup process / server)

    def acknowledge(self, rid: str, verdict: str, now: datetime, cfg: Config):
        self.ledger = state_mod.acknowledge(self.ledger, rid, verdict, now)
        if verdict == state_mod.DONE:
            self._log(f"DONE {rid}", now)
            self.candles.append(f"{rid} — done, {now.strftime('%a %I:%M%p')}")
            actions.notify("Nudge", "Logged. Well done, hunny.")
        else:
            self._log(f"DIDNT {rid}", now)
            actions.notify("Nudge", voice.pick(voice.DIDNT_LINES))
        self._save_ledger()

    def snooze(self, rid: str, minutes: int, now: datetime):
        until = now + __import__("datetime").timedelta(minutes=minutes)
        self.ledger = state_mod.snooze(self.ledger, rid, until, now)
        self._log(f"SNOOZE {rid} {minutes}m", now)
        actions.notify("Nudge", voice.pick(voice.SNOOZE_LINES))
        self._save_ledger()

    # ---- lifecycle

    def run(self):
        cfg = self._config()
        self._log("daemon started", datetime.now())
        while True:
            try:
                self.tick(datetime.now())
            except Exception as exc:  # never die mid-tick
                self._log(f"tick error: {exc!r}", datetime.now())
            time_mod.sleep(max(5, cfg.tick_seconds))


def test_fire(base_dir: Path | None = None, state_dir: Path | None = None) -> list[str]:
    """Drive one fake reminder through all three gears in seconds."""
    d = Daemon(base_dir, state_dir)
    taken = []
    t0 = datetime.now()
    taken += d.tick(t0)
    taken += d.tick(t0 + __import__("datetime").timedelta(minutes=11))
    taken += d.tick(t0 + __import__("datetime").timedelta(minutes=22))
    return taken
