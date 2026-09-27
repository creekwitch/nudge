"""Phase 3: popup handshake — verdicts flow back through the file protocol."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from nudge import actions, daemon as daemon_mod
from nudge import state as s
from nudge.models import APPOINTMENT, Config, Reminder
from test_daemon import Recorder, env, write_config, write_reminders, MON  # noqa: F401


def test_verdict_file_roundtrip(tmp_path):
    vf = tmp_path / "popup-verdicts.jsonl"
    vf.write_text(json.dumps({"id": "a", "verdict": "done", "snooze_min": None}) + "\n"
                  + json.dumps({"id": "b", "verdict": "snooze", "snooze_min": 30}) + "\n"
                  + "\nGARBAGE LINE\n")
    got = actions.poll_verdicts(tmp_path)
    assert got == [{"id": "a", "verdict": "done", "snooze_min": None},
                   {"id": "b", "verdict": "snooze", "snooze_min": 30}]
    assert actions.poll_verdicts(tmp_path) == []  # cleared after read


def test_popup_done_verdict_closes_cycle(env):
    base, state_dir, rec = env
    write_config(base)
    write_reminders(base, Reminder(id="a", type=APPOINTMENT, when=MON, text="Dentist"))
    d = daemon_mod.Daemon(base, state_dir)
    d.tick(MON)
    d.tick(MON + timedelta(minutes=22))          # gear 3 -> popup spawned
    # simulate the popup writing a Done verdict
    (state_dir / "popup-verdicts.jsonl").write_text(
        json.dumps({"id": "a", "verdict": "done", "snooze_min": None}) + "\n")
    taken = d.tick(MON + timedelta(minutes=23))
    assert "popup done a" in taken
    assert s.entry(d.ledger, "a")["verdict"] == "done"
    assert d.candles and "a — done" in d.candles[0]   # the Witness saw it


def test_popup_snooze_verdict_arms_snooze(env):
    base, state_dir, rec = env
    write_config(base)
    write_reminders(base, Reminder(id="a", type=APPOINTMENT, when=MON, text="Dentist"))
    d = daemon_mod.Daemon(base, state_dir)
    d.tick(MON)
    d.tick(MON + timedelta(minutes=22))
    (state_dir / "popup-verdicts.jsonl").write_text(
        json.dumps({"id": "a", "verdict": "snooze", "snooze_min": 30}) + "\n")
    d.tick(MON + timedelta(minutes=23))
    e = s.entry(d.ledger, "a")
    assert e["snoozed_until"] is not None and e["gear"] == 0
    # and during the snooze: silent
    rec.calls.clear()
    d.tick(MON + timedelta(minutes=30))
    assert not rec.calls


def test_popup_queue_contains_all_gear3_reminders(env):
    base, state_dir, rec = env
    write_config(base)
    write_reminders(base,
                    Reminder(id="a", type=APPOINTMENT, when=MON, text="Dentist"),
                    Reminder(id="b", type=APPOINTMENT, when=MON, text="Doc"))
    d = daemon_mod.Daemon(base, state_dir)
    d.tick(MON)
    d.tick(MON + timedelta(minutes=22))
    popups = [c for c in rec.calls if c[0] == "popup"]
    assert popups and set(popups[-1][1]) == {"a", "b"}   # ONE popup, whole queue


def test_spawn_replaces_stale_popup(tmp_path, monkeypatch):
    """One popup rule: spawning kills any previous popup first."""
    import subprocess as sp  # noqa: F401
    captured = {}
    class FakePopen:
        def __init__(self, argv, **kw): captured["argv"] = argv
    killed = []
    monkeypatch.setattr(actions, "_kill_stale_popups",
                        lambda: killed.append("killed"))
    monkeypatch.setattr(actions.subprocess, "Popen", FakePopen)
    monkeypatch.setenv("NUDGE_STATE", str(tmp_path))
    actions.spawn_popup([{"id": "x", "text": "T", "phrase": "p", "note": ""}], Config())
    assert killed == ["killed"]


def test_kill_stale_popups_never_raises(tmp_path, monkeypatch):
    import subprocess as sp
    def boom(*a, **k):
        raise sp.TimeoutExpired(cmd="pgrep", timeout=5)
    monkeypatch.setattr(actions.subprocess, "run", boom)
    actions._kill_stale_popups()  # must not raise


def test_kill_stale_popups_kills_listed_pids(tmp_path, monkeypatch):
    import subprocess as sp
    seen = []
    class FakeOut:
        stdout = "1234\n 5678\n notapid \n"
    monkeypatch.setattr(actions.subprocess, "run", lambda *a, **k: FakeOut())
    monkeypatch.setattr(actions.os, "kill",
                        lambda pid, sig: seen.append(pid))
    monkeypatch.setattr(actions.time, "sleep", lambda s: None)
    actions._kill_stale_popups()
    assert seen == [1234, 5678]  # non-numeric tokens skipped


def test_spawn_popup_writes_request(tmp_path, monkeypatch):
    captured = {}
    class FakePopen:
        def __init__(self, argv, **kw): captured["argv"] = argv
    monkeypatch.setattr(actions, "_kill_stale_popups", lambda: None)
    monkeypatch.setattr(actions.subprocess, "Popen", FakePopen)
    monkeypatch.setenv("NUDGE_STATE", str(tmp_path))
    cfg = Config(popup_corner="top-left", chime_repeat_s=42)
    actions.spawn_popup([{"id": "x", "text": "T", "phrase": "p", "note": ""}], cfg)
    req = json.loads((tmp_path / "popup-request.json").read_text())
    assert req["corner"] == "top-left"
    assert req["snooze_options"] == [5, 10, 30, 60]
    assert req["chime_repeat_s"] == 42
    assert req["reminders"][0]["id"] == "x"
    assert "popup.py" in captured["argv"][1]


def test_spawn_popup_passes_chime_volume(tmp_path, monkeypatch):
    """The popup plays its own repeated chime, so it needs the volume too —
    a gentle volume set in config must reach the popup, not just gear 2/3."""
    captured = {}

    class FakePopen:
        def __init__(self, argv, **kw): captured["argv"] = argv
    monkeypatch.setattr(actions, "_kill_stale_popups", lambda: None)
    monkeypatch.setattr(actions.subprocess, "Popen", FakePopen)
    monkeypatch.setenv("NUDGE_STATE", str(tmp_path))
    cfg = Config(chime_volume=0.12)
    actions.spawn_popup([{"id": "x", "text": "T", "phrase": "p", "note": ""}], cfg)
    req = json.loads((tmp_path / "popup-request.json").read_text())
    assert req["chime_volume"] == 0.12


def test_spawn_popup_passes_chime_enabled_flag(tmp_path, monkeypatch):
    """Regression: turning the chime off must reach the POPUP, not just the
    daemon. The popup repeats the sound every chime_repeat_s while open, so a
    chime:false that only muted the daemon would keep chiming at the person
    it was meant to protect."""
    captured = {}

    class FakePopen:
        def __init__(self, argv, **kw): captured["argv"] = argv
    monkeypatch.setattr(actions, "_kill_stale_popups", lambda: None)
    monkeypatch.setattr(actions.subprocess, "Popen", FakePopen)
    monkeypatch.setenv("NUDGE_STATE", str(tmp_path))
    actions.spawn_popup([{"id": "x", "text": "T", "phrase": "p", "note": ""}],
                        Config(chime=False))
    req = json.loads((tmp_path / "popup-request.json").read_text())
    assert req["chime_enabled"] is False


def test_chime_passes_volume_to_paplay(monkeypatch):
    """chime(volume) must hand paplay a --volume on its 0..65536 scale."""
    calls = []
    monkeypatch.setattr(actions, "CHIME_FILE", __import__("pathlib").Path(__file__))
    monkeypatch.setattr(actions.shutil, "which", lambda n: "/usr/bin/paplay")
    monkeypatch.setattr(actions.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    actions.chime(0.25)
    assert calls and calls[0][0] == "paplay"
    assert "--volume=16384" in " ".join(calls[0])   # 0.25 * 65536


def test_notify_suppresses_desktop_sound(monkeypatch):
    """Regression: notify() must pass the suppress-sound hint.

    Cinnamon's messageTray plays a notification sound whenever urgency >= HIGH
    *regardless of the sound settings*
    (`if (!silent || urgency >= HIGH) soundManager.play('notification')`).
    Nudge's gear-2 alert is `-u critical`, so without this hint the desktop
    makes a noise on every escalation even with every chime and sound setting
    off — the bug where turning the Nudge chime off did not stop the sound.
    """
    calls = []
    monkeypatch.setattr(actions.subprocess, "run",
                        lambda argv, **kw: calls.append(argv))
    actions.notify("Nudge", "body", critical=True)
    flat = " ".join(calls[0])
    assert "suppress-sound" in flat
    assert "critical" in flat
