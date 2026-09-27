#!/usr/bin/env python3
"""Phase 0 spike: GTK popup probe for MATE/X11.

Verifies: always-on-top, all workspaces, no taskbar entry, no close X,
corner pinning. Expected verdicts land in stdout; click the buttons to
see them print. Kills with Ctrl+C.
"""
import sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk

CORNERS = {
    "bottom-right": (Gtk.CornerType.BOTTOM_RIGHT),
    "bottom-left": (Gtk.CornerType.BOTTOM_LEFT),
}

def build(corner):
    win = Gtk.Window(type=Gtk.WindowType.POPUP)  # frameless, no WM decorations
    win.set_title("nudge-spike")  # POPUP windows usually skip taskbar; set anyway
    win.set_keep_above(True)
    win.stick()                      # all workspaces (X11)
    win.set_skip_taskbar_hint(True)
    win.set_skip_pager_hint(True)
    win.set_type_hint(Gdk.WindowTypeHint.DOCK)
    win.set_accept_focus(True)
    # corner pin: position at bottom-right of primary monitor
    d = Gdk.Display.get_default()
    mon = d.get_primary_monitor() or d.get_monitor(0)
    geo = mon.get_geometry()
    w, h = 340, 180
    x, y = geo.x + geo.width - w - 16, geo.y + geo.height - h - 48
    win.move(x, y)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(12); box.set_margin_bottom(12)
    box.set_margin_start(12); box.set_margin_end(12)
    lbl = Gtk.Label(label="Spike: stretch — it's been a while, hunny.")
    lbl.set_line_wrap(True)
    box.pack_start(lbl, True, True, 0)
    row = Gtk.Box(spacing=6)
    for name in ("Done", "Didn't do it", "Snooze"):
        b = Gtk.Button(label=name)
        b.connect("clicked", lambda _b, n=name: (print(f"VERDICT: {n}", flush=True)))
        row.pack_start(b, True, True, 0)
    box.pack_start(row, False, False, 0)
    win.add(box)
    win.show_all()
    return win

if __name__ == "__main__":
    corner = sys.argv[1] if len(sys.argv) > 1 else "bottom-right"
    build(corner)
    print("popup up — click a button, check workspaces/taskbar, then Ctrl+C", flush=True)
    Gtk.main()
