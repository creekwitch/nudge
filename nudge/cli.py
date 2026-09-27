"""nudge — CLI entrypoint. start | status | list | add | test-fire."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import schedule, store, voice
from .models import ConfigError
from .daemon import Daemon


def _die(msg: str) -> None:
    print(f"nudge: {msg}", file=sys.stderr)
    sys.exit(2)


def cmd_status(base, state_dir) -> int:
    d = Daemon(base, state_dir)
    cfg = d._config()
    now = datetime.now()
    quiet = schedule.is_quiet(cfg.quiet_hours, now)
    print(f"{now.strftime('%a %H:%M')} — quiet hours: {'YES' if quiet else 'no'}")
    for r in d._reminders():
        e = __import__("nudge.state", fromlist=["entry"]).entry(d.ledger, r.id)
        flags = []
        if e["deferred"]:
            flags.append("deferred (quiet hours)")
        if e["gear"]:
            flags.append(f"gear {e['gear']}")
        if e["snoozed_until"]:
            flags.append(f"snoozed until {e['snoozed_until'][11:16]}")
        nf = schedule.next_fire(r, now, state_mod_ts(e))
        when = nf.strftime("%a %H:%M") if nf else "(past)"
        print(f"  {r.id:<14} {r.type:<12} next: {when:<12} {' '.join(flags)}")
    return 0


def state_mod_ts(e):
    from nudge import state as s
    return s.parse_ts(e["last_fired"]) if e["gear"] else None


def cmd_log(args, state_dir) -> int:
    """Show the firing/ack log — for tuning, not judgment (SPEC §8)."""
    from nudge import store
    path = (state_dir or store.DEFAULT_STATE_DIR) / "log"
    if not path.exists():
        print("no log yet — nothing has fired")
        return 0
    lines = path.read_text().splitlines()
    n = args.lines
    shown = lines[-n:] if n else lines
    if n and len(lines) > n:
        print(f"(last {n} of {len(lines)} — nudge log --lines N for more)")
    for line in shown:
        print(line)
    return 0


def cmd_list(base) -> int:
    rs = store.load_reminders(store.reminders_path(base))
    if not rs:
        print(voice.pick(voice.LIST_EMPTY))
        return 0
    for r in rs:
        print(f"{r.id:<14} {r.type:<12} {r.text}")
    return 0


def cmd_add(args, base) -> int:
    p = store.reminders_path(base)
    rs = store.load_reminders(p)
    raw = {"id": args.id, "type": args.type, "text": args.text}
    if args.type == "appointment":
        raw["when"] = args.when
    elif args.type == "chore":
        raw["schedule"] = args.schedule
    else:
        raw["every"] = args.every
        if args.active_only:
            raw["active_only"] = True
    if args.note:
        raw["note"] = args.note
    if args.hard:
        raw["hard"] = True
    from .models import Reminder
    rs.append(Reminder.from_dict(raw))  # validates
    if any(r.id == raw["id"] for r in rs[:-1]):
        _die(f"id already exists: {raw['id']}")
    store.save_reminders(rs, p)
    print(f"added {raw['id']} (the daemon picks it up on its next tick)")
    return 0


def cmd_test_fire(base, state_dir) -> int:
    from .daemon import test_fire
    taken = test_fire(base, state_dir)
    for t in taken:
        print(t)
    if not taken:
        print("nothing due (add a test reminder or use: nudge add --type nudge)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nudge",
                                 description="A care reminder daemon.")
    ap.add_argument("--home", type=Path, default=None,
                    help="config dir (default ~/.config/nudge)")
    ap.add_argument("--state", type=Path, default=None,
                    help="state dir (default ~/.local/state/nudge)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("start", help="run the daemon (foreground; systemd for real use)")
    sub.add_parser("status", help="what's pending, deferred, next")
    sub.add_parser("list", help="list reminders")
    add = sub.add_parser("add", help="add a reminder (the add-by-chat path)")
    add.add_argument("id")
    add.add_argument("type", choices=["appointment", "chore", "nudge"])
    add.add_argument("text")
    add.add_argument("--when", help="appointment: 'YYYY-MM-DD HH:MM'")
    add.add_argument("--schedule", help="chore: 'mon,wed,fri 13:00'")
    add.add_argument("--every", help="nudge: '90m' or '2h'")
    add.add_argument("--active-only", action="store_true")
    add.add_argument("--note")
    add.add_argument("--hard", action="store_true")
    sub.add_parser("test-fire", help="drive one fake reminder through all gears")
    lg = sub.add_parser("log", help="show firings + verdicts (for tuning)")
    lg.add_argument("--lines", type=int, default=0, help="show only the last N")
    ui = sub.add_parser("ui", help="open the settings panel (localhost web UI)")
    ui.add_argument("--port", type=int, default=8130)
    args = ap.parse_args(argv)

    base, state_dir = args.home, args.state
    try:
        if args.cmd == "start":
            Daemon(base, state_dir).run()
        elif args.cmd == "status":
            return cmd_status(base, state_dir)
        elif args.cmd == "list":
            return cmd_list(base)
        elif args.cmd == "add":
            return cmd_add(args, base)
        elif args.cmd == "test-fire":
            return cmd_test_fire(base, state_dir)
        elif args.cmd == "log":
            return cmd_log(args, state_dir)
        elif args.cmd == "ui":
            import webbrowser
            from .server import serve
            webbrowser.open(f"http://127.0.0.1:{args.port}")
            serve(base, state_dir, port=args.port)
        else:
            ap.print_help()
    except ConfigError as e:
        _die(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
