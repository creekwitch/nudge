"""Real-world side effects: notifications, chime, popup spawn, idle time.

All subprocess/DBus wrappers live here, behind small functions the daemon
imports — tests monkeypatch these (AGENTS.md: pure logic never spawns).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CHIME_FILE = (Path(__file__).resolve().parent.parent / "sounds" / "chime.ogg")
if not CHIME_FILE.exists():  # installed layout: sounds/ sits beside the package
    CHIME_FILE = Path(__file__).resolve().parent.parent.parent / "sounds" / "chime.ogg"


def notify(title: str, body: str, critical: bool = False) -> None:
    """Gear 1/2 notification. Critical persists until interacted.

    The `suppress-sound` hint is load-bearing: Cinnamon's messageTray always
    plays a notification sound when urgency >= HIGH *regardless of the sound
    settings* (`if (!silent || urgency >= HIGH) soundManager.play(...)`).
    Nudge's gear-2 alert is critical, so without this hint the desktop makes
    a noise on every escalation — even with every chime and sound setting
    turned off. Sound is the desktop's business here, not ours; the popup
    and the banner carry the reminder.
    """
    argv = ["notify-send", title, body,
            "--hint=boolean:suppress-sound:true",
            "--expire-time=0" if critical else "--expire-time=10000"]
    if critical:
        argv.insert(1, "-u")
        argv.insert(2, "critical")
    subprocess.run(argv, check=False)


def chime(volume: float = 0.35) -> None:
    """One soft chime, if the sound exists and paplay is present.

    volume is a 0.0..1.0 fraction, mapped onto paplay's linear 0..65536
    scale. The chime is a nudge, not an alarm — it plays well below full
    volume by default so it does not startle (loud is a sensory problem for
    the person this cares for).
    """
    if not CHIME_FILE.exists() or not shutil.which("paplay"):
        return
    pct = max(0.0, min(1.0, float(volume)))
    level = int(round(pct * 65536))
    subprocess.run(["paplay", f"--volume={level}", str(CHIME_FILE)], check=False)


def spawn_popup(queue: list[dict], cfg) -> None:
    """Start the Gear 3 popup process with the current due-queue.

    File handshake: daemon writes request.json, popup writes verdict lines
    the daemon polls on later ticks (popup crashes can't take the scheduler
    down).

    Stale-request guard: if an OLD popup is still alive, kill it first and
    unlink its request file — one popup, always the freshest queue (the new
    request already contains every still-unhandled reminder, because the
    daemon rebuilds the queue from the ledger each spawn).
    """
    popup = Path(__file__).resolve().parent / "popup.py"
    state = Path(os.environ.get(
        "NUDGE_STATE", str(Path.home() / ".local" / "state" / "nudge")))
    state.mkdir(parents=True, exist_ok=True)
    req_file = state / "popup-request.json"
    verdict_file = state / "popup-verdicts.jsonl"
    _kill_stale_popups()
    req_file.write_text(json.dumps({
        "reminders": queue,
        "corner": cfg.popup_corner,
        "snooze_options": list(cfg.snooze_options),
        "chime_repeat_s": cfg.chime_repeat_s,
        "chime_volume": cfg.chime_volume,
        "chime_enabled": bool(cfg.chime),
        "verdict_file": str(verdict_file),
        "request_file": str(req_file),
    }))
    subprocess.Popen(
        ["/usr/bin/python3", str(popup), str(req_file)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # NB: system python, never sys.executable — a venv python has no `gi`
    # and the popup dies silently (found by the live replacement test).


def _kill_stale_popups() -> None:
    """Kill any running popup process and clear its request file."""
    try:
        out = subprocess.run(["pgrep", "-f", "nudge/popup.py"],
                             capture_output=True, text=True, timeout=5)
        for pid in out.stdout.split():
            if pid.strip().isdigit():
                try:
                    os.kill(int(pid), 15)
                except (ProcessLookupError, PermissionError, ValueError):
                    pass
        if out.stdout.strip():
            # pending verdicts from the killed popup stay valid — the daemon
            # polls them on the next tick regardless of the popup's death.
            time.sleep(0.3)  # give the killed process a moment to exit
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


def poll_verdicts(state_dir: Path) -> list[dict]:
    """Read and clear popup verdict lines. Never raises."""
    vf = state_dir / "popup-verdicts.jsonl"
    out = []
    if vf.exists():
        for line in vf.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        vf.unlink(missing_ok=True)
    return out


def idle_ms(display: str = ":0") -> int | None:
    """User input idle time in ms via XScreenSaver extension (libXss).

    Returns None when idle time is unknowable — callers treat that as
    'user active' (active_only degrades to always-fire, per SPEC §6).
    """
    try:
        x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
        xss = ctypes.CDLL(ctypes.util.find_library("Xss"))
    except (OSError, TypeError):
        return None

    class XScreenSaverInfo(ctypes.Structure):
        _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int),
                    ("kind", ctypes.c_int), ("til_or_since", ctypes.c_ulong),
                    ("idle", ctypes.c_ulong), ("eventMask", ctypes.c_ulong)]

    # restype/argtypes MUST be set before calling (segfault otherwise — SPEC §6)
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
    xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                          ctypes.POINTER(XScreenSaverInfo)]
    xss.XScreenSaverQueryInfo.restype = ctypes.c_int

    d = x11.XOpenDisplay(display.encode())
    if not d:
        return None
    info = xss.XScreenSaverAllocInfo()
    if not xss.XScreenSaverQueryInfo(d, x11.XDefaultRootWindow(d), info):
        return None
    return int(info.contents.idle)
