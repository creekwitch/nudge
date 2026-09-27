"""Localhost HTTP API + static UI for the settings/control panel."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import actions, candle, schedule, state as state_mod, store, voice
from .daemon import Daemon
from .models import (APPOINTMENT, CHORE, NUDGE, Config, ConfigError,
                     QuietHours, Reminder, TYPES, WEEKDAYS)

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def build_handler(d: Daemon):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        # ---- helpers

        def _send(self, code: int, body: bytes, ctype: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj).encode())

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n))
            except json.JSONDecodeError:
                raise ValueError("invalid JSON body")

        # ---- routing

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/" or path == "/index.html":
                return self._send(200, (UI_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/app.js":
                return self._send(200, (UI_DIR / "app.js").read_bytes(), "text/javascript")
            if path == "/app.css":
                return self._send(200, (UI_DIR / "app.css").read_bytes(), "text/css")
            if path == "/theme-ledger.css":
                # additive skin; app.css stays the default system
                sheet = UI_DIR / "theme-ledger.css"
                if not sheet.exists():
                    return self._json(404, {"error": "no theme"})
                return self._send(200, sheet.read_bytes(), "text/css")
            if path == "/api/reminders":
                now = datetime.now()
                out = []
                for r in d._reminders():
                    e = state_mod.entry(d.ledger, r.id)
                    nf = schedule.next_fire(r, now, state_mod.parse_ts(e["last_fired"]))
                    out.append({**r.to_dict(),
                                "next_fire": nf.isoformat() if nf else None,
                                "gear": e["gear"], "deferred": e["deferred"],
                                "verdict": e["verdict"]})
                return self._json(200, {"reminders": out, "types": TYPES, "weekdays": WEEKDAYS})
            if path == "/api/config":
                cfg = d._config()
                return self._json(200, {
                    "gear2_delay_min": cfg.gear2_delay_min,
                    "gear3_delay_min": cfg.gear3_delay_min,
                    "snooze_options": list(cfg.snooze_options),
                    "chime": cfg.chime, "chime_repeat_s": cfg.chime_repeat_s,
                    "popup_corner": cfg.popup_corner,
                    "quiet_hours": cfg.quiet_hours.to_dict(),
                    "witness": {"enabled": cfg.witness_enabled},
                    "telling": {"enabled": cfg.telling_enabled, "hour": cfg.telling_hour},
                })
            if path.startswith("/api/log"):
                # for the Status tab — tuning, not judgment
                lines = 60
                for part in (self.path.split("?")[1] if "?" in self.path else "").split("&"):
                    if part.startswith("lines=") and part[6:].isdigit():
                        lines = min(500, max(1, int(part[6:])))
                logp = d.state_dir / "log"
                if not logp.exists():
                    return self._json(200, {"lines": []})
                try:
                    tail = logp.read_text(errors="replace").splitlines()[-lines:]
                except OSError as e:
                    return self._json(500, {"error": str(e)})
                return self._json(200, {"lines": tail})
            if path.startswith("/api/calendar"):
                now = datetime.now()
                cfg = d._config()
                # ?year=YYYY&month=M — defaults to current month
                year, month = now.year, now.month
                for part in self.path.split("?")[1].split("&"):
                    if part.startswith("year=") and part[5:].isdigit():
                        year = int(part[5:])
                    elif part.startswith("month=") and part[6:].isdigit():
                        month = int(part[6:])
                if not (1 <= month <= 12):
                    return self._json(400, {"error": "month must be 1..12"})
                events = []
                for r in d._reminders():
                    e = state_mod.entry(d.ledger, r.id)
                    occs = schedule.occurrences_in_month(
                        r, year, month, state_mod.parse_ts(e["last_fired"]))
                    # An interval nudge (every 90m) would claim a hundred slots a
                    # month and drown the month view. The calendar answers "what
                    # is ON this day", not "how many times will this ping" — so a
                    # nudge contributes one entry per day, at its first fire, and
                    # carries `repeats` so the UI can say so.
                    if r.type == "nudge":
                        first_by_day = {}
                        for occ in occs:
                            first_by_day.setdefault(occ.day, occ)
                        occs = [first_by_day[k] for k in sorted(first_by_day)]
                    for occ in occs:
                        ev = {
                            "id": r.id, "text": r.text, "type": r.type,
                            "at": occ.isoformat(timespec="minutes"),
                            "past": occ < now,
                        }
                        if r.type == "nudge" and r.every_min:
                            ev["repeats"] = schedule.format_every(r.every_min) \
                                if hasattr(schedule, "format_every") else f"{r.every_min}m"
                        events.append(ev)
                events.sort(key=lambda ev: ev["at"])
                import calendar as cal_mod
                return self._json(200, {
                    "year": year, "month": month,
                    "month_name": cal_mod.month_name[month],
                    "today": now.date().isoformat(),
                    "first_weekday": (datetime(year, month, 1).weekday() + 1) % 7,  # Sunday=0 grid
                    "days_in_month": cal_mod.monthrange(year, month)[1],
                    "events": events,
                })
            if path == "/api/status":
                now = datetime.now()
                cfg = d._config()
                quiet = schedule.is_quiet(cfg.quiet_hours, now)
                pending, deferred, upcoming = [], [], None
                for r in d._reminders():
                    e = state_mod.entry(d.ledger, r.id)
                    if e["deferred"]:
                        deferred.append(r.id)
                    elif e["gear"]:
                        pending.append({"id": r.id, "gear": e["gear"]})
                    nf = schedule.next_fire(r, now, state_mod.parse_ts(e["last_fired"]))
                    if nf and (upcoming is None or nf < upcoming[1]):
                        upcoming = (r.id, nf)
                return self._json(200, {
                    "now": now.isoformat(timespec="minutes"),
                    "quiet": quiet,
                    "pending": pending, "deferred": deferred,
                    "next": {"id": upcoming[0], "at": upcoming[1].isoformat(timespec="minutes")} if upcoming else None,
                })
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            try:
                body = self._body()
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            path = self.path.split("?")[0]
            if path == "/api/reminders":
                try:
                    r = Reminder.from_dict(body)
                except ConfigError as e:
                    return self._json(400, {"error": str(e)})
                rs = d._reminders()
                if any(x.id == r.id for x in rs):
                    return self._json(409, {"error": f"id exists: {r.id}"})
                rs.append(r)
                store.save_reminders(rs, store.reminders_path(d.base))
                return self._json(201, r.to_dict())
            if path == "/api/popup-verdict":
                # A verdict from anywhere (the GTK popup's sibling clients,
                # the desklet). Written as a verdict line the daemon's own
                # poll picks up — one path, one owner (the daemon writes the
                # ledger; this process only hands it a line, like the popup).
                rid = body.get("id")
                verdict = body.get("verdict")
                if not rid or verdict not in ("done", "didnt", "snooze"):
                    return self._json(400, {"error": "need id and verdict in "
                                                     "('done','didnt','snooze')"})
                rs = d._reminders()
                if not any(x.id == rid for x in rs):
                    return self._json(404, {"error": f"no reminder {rid!r}"})
                line = {"id": rid, "verdict": verdict,
                        "snooze_min": body.get("snooze_min")}
                vf = d.state_dir / "popup-verdicts.jsonl"
                vf.parent.mkdir(parents=True, exist_ok=True)
                with vf.open("a") as f:
                    f.write(json.dumps(line) + "\n")
                return self._json(202, {"queued": line})
            if path == "/api/test-fire":
                rid = body.get("id")
                rs = d._reminders()
                r = next((x for x in rs if x.id == rid), None)
                if not r:
                    return self._json(404, {"error": f"no reminder {rid!r}"})
                now = datetime.now()
                # reload the ledger: the daemon process owns this file and
                # writes it every tick — never clobber its fresh state with
                # our snapshot.
                d.ledger = store.load_ledger(store.ledger_path(d.state_dir))
                phrase = voice.render(voice.FIRE, r.text, r.note,
                                      state_mod.entry(d.ledger, rid)["last_phrase"])
                actions.notify("Nudge", phrase)
                self._json(200, {"fired": rid, "phrase": phrase})
                return None
            return self._json(404, {"error": "not found"})

        def do_PATCH(self):
            try:
                body = self._body()
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            rid = self.path.split("?")[0].rsplit("/", 1)[-1]
            rs = d._reminders()
            for i, r in enumerate(rs):
                if r.id == rid:
                    merged = {**r.to_dict(), **{k: v for k, v in body.items() if k != "id"}}
                    try:
                        rs[i] = Reminder.from_dict(merged)
                    except ConfigError as e:
                        return self._json(400, {"error": str(e)})
                    store.save_reminders(rs, store.reminders_path(d.base))
                    return self._json(200, rs[i].to_dict())
            return self._json(404, {"error": f"no reminder {rid!r}"})

        def do_DELETE(self):
            rid = self.path.split("?")[0].rsplit("/", 1)[-1]
            rs = d._reminders()
            keep = [r for r in rs if r.id != rid]
            if len(keep) == len(rs):
                return self._json(404, {"error": f"no reminder {rid!r}"})
            store.save_reminders(keep, store.reminders_path(d.base))
            return self._json(200, {"deleted": rid})

        def do_PUT(self):
            try:
                body = self._body()
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            if self.path.split("?")[0] == "/api/config":
                try:
                    cfg = Config.from_dict(body)
                except ConfigError as e:
                    return self._json(400, {"error": str(e)})
                store.save_config(cfg, store.config_path(d.base))
                return self._json(200, {"saved": True})
            return self._json(404, {"error": "not found"})

    return Handler


def serve(base=None, state_dir=None, host="127.0.0.1", port=8130):
    d = Daemon(base, state_dir)
    httpd = ThreadingHTTPServer((host, port), build_handler(d))
    print(f"nudge UI on http://{host}:{port}")
    httpd.serve_forever()
