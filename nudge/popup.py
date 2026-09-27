#!/usr/bin/env python3
"""Gear 3: the persistent popup. A separate GTK process.

Protocol (file handshake — the daemon owns the ledger):
  argv[1] = request JSON:  {"reminders": [{id, text, phrase, gear}],
                            "corner": "bottom-right",
                            "snooze_options": [5,10,30,60],
                            "chime_repeat_s": 60,
                            "verdict_file": "/path/verdict.json",
                            "request_file": "/path/request.json"}
  The popup writes ONE verdict at a time to verdict_file:
      {"id": ..., "verdict": "done"|"didnt", "snooze_min": int|null}
  then removes itself from the queue and continues with the rest.
  When the queue empties, the popup exits and deletes request_file.

NO close X, NO Escape-dismiss — the only exits are Done / Didn't do it /
Snooze (constitution #3). Escape opens the Snooze menu instead.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

CORNERS = ("bottom-right", "bottom-left", "top-right", "top-left")

CSS = b"""
window { background: rgba(30,30,46,0.96); border-radius: 10px; }
.title { font-weight: bold; font-size: 13px; color: #f5c2e7; }
.body { font-size: 13px; color: #cdd6f4; }
.note { font-size: 11px; color: #a6adc8; font-style: italic; }
.count { font-size: 11px; color: #a6adc8; }
"""


def corner_xy(corner: str, w: int, h: int, margin: int = 16) -> tuple[int, int]:
    d = Gdk.Display.get_default()
    mon = d.get_primary_monitor() or d.get_monitor(0)
    geo = mon.get_geometry()
    if corner == "bottom-right":
        return geo.x + geo.width - w - margin, geo.y + geo.height - h - margin * 3
    if corner == "bottom-left":
        return geo.x + margin, geo.y + geo.height - h - margin * 3
    if corner == "top-right":
        return geo.x + geo.width - w - margin, geo.y + margin
    return geo.x + margin, geo.y + margin  # top-left


class Popup(Gtk.Window):
    def __init__(self, req: dict):
        # MUST be TOPLEVEL + undecorated, never WindowType.POPUP: a POPUP
        # window is a menu-type override-redirect window that GTK never maps
        # as a real top-level, so the process would run, "show", and remain
        # invisible — the exact silent-death bug found 2026-09-26 (observed
        # no popup at all). Framelessness comes from set_decorated(False).
        super().__init__(type=Gtk.WindowType.TOPLEVEL)  # real mapped window
        self.set_decorated(False)  # frameless: no close X by construction
        # A title makes the window findable by session tools (wmctrl/xwininfo)
        # — tools/check-popup.sh asserts the window is MAPPED, which is the
        # only thing that distinguishes "popup shown" from "process alive".
        self.set_title("Nudge")
        self.req = req
        self.queue: list[dict] = list(req.get("reminders", []))
        self.verdict_file = Path(req["verdict_file"])
        self.request_file = Path(req["request_file"])
        self.chime_ms = max(10, int(req.get("chime_repeat_s", 60)) * 1000)
        self.chime_volume = float(req.get("chime_volume", 0.35))
        # chime off must reach the POPUP too, not just the daemon: the popup
        # is what repeats the sound every chime_repeat_s while it is open.
        self.chime_enabled = bool(req.get("chime_enabled", True))

        self.set_keep_above(True)
        self.stick()  # all workspaces
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_accept_focus(True)
        self.set_default_size(360, 10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(14); box.set_margin_bottom(14)
        box.set_margin_start(14); box.set_margin_end(14)
        self.title = Gtk.Label()
        self.title.get_style_context().add_class("title")
        self.title.set_halign(Gtk.Align.START)
        self.body = Gtk.Label()
        self.body.get_style_context().add_class("body")
        self.body.set_line_wrap(True)
        self.body.set_xalign(0)
        self.note = Gtk.Label()
        self.note.get_style_context().add_class("note")
        self.note.set_line_wrap(True)
        self.note.set_halign(Gtk.Align.START)
        self.count = Gtk.Label()
        self.count.get_style_context().add_class("count")
        self.count.set_halign(Gtk.Align.END)
        box.pack_start(self.title, False, False, 0)
        box.pack_start(self.body, True, True, 0)
        box.pack_start(self.note, False, False, 0)
        box.pack_start(self.count, False, False, 0)

        row = Gtk.Box(spacing=6)
        b_done = Gtk.Button(label="Done")
        b_done.get_style_context().add_class("suggested-action")
        b_done.connect("clicked", self._on_done)
        b_didnt = Gtk.Button(label="Didn't do it")
        b_didnt.connect("clicked", self._on_didnt)
        b_snooze = Gtk.Button(label="Snooze")
        b_snooze.connect("clicked", self._on_snooze_menu)
        for b in (b_done, b_didnt, b_snooze):
            row.pack_start(b, True, True, 0)
        box.pack_start(row, False, False, 0)

        self.snooze_menu = Gtk.Menu()
        for m in req.get("snooze_options", [5, 10, 30, 60]):
            item = Gtk.MenuItem(label=f"{m} minutes")
            item.connect("activate", self._on_snooze, m)
            self.snooze_menu.append(item)
        self.snooze_menu.show_all()

        self.add(box)
        self.connect("key-press-event", self._on_key)
        self.show_all()
        self._paint()
        GLib.timeout_add(self.chime_ms, self._chime_tick)

    # ---- queue painting

    def _paint(self):
        if not self.queue:
            Gtk.main_quit()
            return False
        cur = self.queue[0]
        self.title.set_text(f"⏳ {cur['text']}")
        self.body.set_text(cur.get("phrase") or cur["text"])
        self.note.set_text(cur.get("note") or "")
        self.note.set_visible(bool(cur.get("note")))
        rest = len(self.queue) - 1
        self.count.set_text(f"{rest} more waiting" if rest else "")
        self.resize(360, 10)
        x, y = corner_xy(self.req.get("corner", "bottom-right"), 380, self.get_allocated_height() or 200)
        self.move(x, y)
        return False

    def _advance(self):
        self.queue.pop(0)
        if not self.queue:
            self.request_file.unlink(missing_ok=True)
            Gtk.main_quit()
        else:
            self._paint()

    # ---- verdicts

    def _write_verdict(self, verdict: str, snooze_min: int | None = None):
        cur = self.queue[0]
        self.verdict_file.parent.mkdir(parents=True, exist_ok=True)
        with self.verdict_file.open("a") as f:
            f.write(json.dumps({"id": cur["id"], "verdict": verdict,
                                "snooze_min": snooze_min}) + "\n")

    def _on_done(self, _b):
        self._write_verdict("done")
        self._advance()

    def _on_didnt(self, _b):
        self._write_verdict("didnt")
        self._advance()

    def _on_snooze(self, _item, minutes):
        self._write_verdict("snooze", minutes)
        self._advance()

    def _on_snooze_menu(self, _b):
        self.snooze_menu.popup_at_widget(_b, Gdk.Gravity.SOUTH, Gdk.Gravity.NORTH, None)

    def _on_key(self, _w, event):
        # No escape-dismiss: Escape opens the Snooze menu (constitution #3)
        if event.keyval == Gdk.KEY_Escape:
            self._on_snooze_menu(None)
            return True
        return False

    def _chime_tick(self):
        if not self.queue:
            return False
        if not self.chime_enabled:
            return True   # chime configured off: stay scheduled, make no sound
        try:
            from nudge.actions import chime
            chime(self.chime_volume)
        except Exception:
            pass
        return True


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: popup.py <request.json>", file=sys.stderr)
        return 2
    req = json.loads(Path(sys.argv[1]).read_text())
    if not req.get("reminders"):
        return 0
    style = Gtk.CssProvider()
    style.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    win = Popup(req)
    win.present()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
