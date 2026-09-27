"""Daemon ticks with actions recorded, never spawned."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from nudge import daemon as daemon_mod
from nudge import store
from nudge.models import APPOINTMENT, CHORE, NUDGE, Config, QuietHours, Reminder


class Recorder:
    def __init__(self):
        self.calls = []

    def notify(self, title, body, critical=False):
        self.calls.append(("notify", title, body, critical))

    def chime(self, volume=0.35):
        self.calls.append(("chime", volume))

    def spawn_popup(self, queue, cfg):
        self.calls.append(("popup", tuple(q["id"] for q in queue)))

    def idle_ms(self):
        return self.idle_value

    def __init_idle(self):
        self.idle_value = 0


@pytest.fixture
def env(tmp_path, monkeypatch):
    base, state_dir = tmp_path / "cfg", tmp_path / "state"
    base.mkdir(); state_dir.mkdir()
    rec = Recorder()
    rec.idle_value = 0
    monkeypatch.setattr(daemon_mod.actions, "notify", rec.notify)
    monkeypatch.setattr(daemon_mod.actions, "chime", rec.chime)
    monkeypatch.setattr(daemon_mod.actions, "spawn_popup", rec.spawn_popup)
    monkeypatch.setattr(daemon_mod.actions, "idle_ms", lambda *a: rec.idle_value)
    monkeypatch.setattr(daemon_mod, "send_pair_ping", lambda cfg, r: True, raising=False)
    return base, state_dir, rec


def write_config(base, **kw):
    cfg = Config(**kw)
    store.save_config(cfg, store.config_path(base))
    return cfg


def write_reminders(base, *reminders):
    store.save_reminders(list(reminders), store.reminders_path(base))


MON = datetime(2026, 9, 28, 13, 0)


def test_appointment_full_gear_walk(env):
    base, state_dir, rec = env
    write_config(base)
    write_reminders(base, Reminder(id="a", type=APPOINTMENT, when=MON, text="Dentist"))
    d = daemon_mod.Daemon(base, state_dir)
    taken = d.tick(MON)
    assert "fire a (gear 1)" in taken
    taken2 = d.tick(MON + timedelta(minutes=11))
    assert "escalate a -> gear 2" in taken2
    taken3 = d.tick(MON + timedelta(minutes=22))
    assert "escalate a -> gear 3 (popup)" in taken3
    kinds = [c[0] for c in rec.calls]
    assert kinds.count("notify") >= 2 and "popup" in kinds and "chime" in kinds
    # gear-2 notification was critical
    assert any(c[0] == "notify" and c[3] for c in rec.calls)


def test_quiet_hours_defer_then_drain(env):
    base, state_dir, rec = env
    # quiet 12:00-14:00; chore at 13:00
    write_config(base, quiet_hours=QuietHours.from_dict({"mon": ["12:00", "14:00"]}))
    write_reminders(base, Reminder(id="c", type=CHORE, schedule="mon 13:00", text="Laundry"))
    d = daemon_mod.Daemon(base, state_dir)
    assert "defer c (quiet hours)" in d.tick(MON)
    assert not any(c[0] == "notify" for c in rec.calls)   # silence, not drop
    # quiet ends at 14:00 -> delivered
    taken = d.tick(MON + timedelta(hours=1))
    assert "deliver deferred c" in taken
    assert any(c[0] == "notify" for c in rec.calls)
    # ledger no longer deferred
    from nudge import state as s
    assert s.entry(d.ledger, "c")["deferred"] is False


def test_appointment_in_quiet_hours_gear1_only(env):
    base, state_dir, rec = env
    write_config(base, quiet_hours=QuietHours.from_dict({"mon": ["12:00", "14:00"]}))
    write_reminders(base, Reminder(id="a", type=APPOINTMENT, when=MON, text="Dentist"))
    d = daemon_mod.Daemon(base, state_dir)
    d.tick(MON)
    d.tick(MON + timedelta(minutes=30))   # would be gear 3 outside quiet
    assert "popup" not in [c[0] for c in rec.calls]       # capped at gear 1
    # hard appointments break through fully
    rec.calls.clear()
    write_reminders(base, Reminder(id="h", type=APPOINTMENT, when=MON, text="Doc", hard=True))
    d2 = daemon_mod.Daemon(base, state_dir)
    d2.tick(MON)
    d2.tick(MON + timedelta(minutes=11))
    d2.tick(MON + timedelta(minutes=22))
    assert "popup" in [c[0] for c in rec.calls]


def test_snooze_reenters_and_reschedules(env):
    base, state_dir, rec = env
    write_config(base)
    write_reminders(base, Reminder(id="n", type=NUDGE, every_min=90, text="Stretch"))
    d = daemon_mod.Daemon(base, state_dir)
    d.tick(MON)
    d.snooze("n", 10, MON + timedelta(minutes=1))
    rec.calls.clear()
    # 5 min into a 10-min snooze: silent
    d.tick(MON + timedelta(minutes=6))
    assert not rec.calls
    # after snooze expiry: fires again (gear 1, fresh clock)
    d.tick(MON + timedelta(minutes=11))
    assert any(c[0] == "notify" for c in rec.calls)


def test_done_lights_candle(env):
    base, state_dir, rec = env
    write_config(base)
    write_reminders(base, Reminder(id="n", type=NUDGE, every_min=90, text="Stretch"))
    d = daemon_mod.Daemon(base, state_dir)
    d.tick(MON)
    d.acknowledge("n", "done", MON + timedelta(minutes=14), d._config())
    assert d.candles and "n — done" in d.candles[0]
    d.acknowledge("n", "didnt", MON + timedelta(minutes=14), d._config())
    assert not any("Well done" in c[2] for c in rec.calls[-1:])


def test_active_only_respects_idle(env):
    base, state_dir, rec = env
    write_config(base)
    write_reminders(base, Reminder(id="s", type=NUDGE, every_min=90, text="Stretch", active_only=True))
    d = daemon_mod.Daemon(base, state_dir)
    rec.idle_value = 400_000          # user away > 5 min
    assert "fire s (gear 1)" not in d.tick(MON)
    rec.idle_value = 1_000            # user active
    assert "fire s (gear 1)" in d.tick(MON)


def test_ui_edits_need_no_restart(env):
    """config/reminders are re-read every tick."""
    base, state_dir, rec = env
    write_config(base, gear2_delay_min=10)
    write_reminders(base, Reminder(id="a", type=APPOINTMENT, when=MON, text="Dentist"))
    d = daemon_mod.Daemon(base, state_dir)
    d.tick(MON)
    # change gear2 delay to 1 min on disk
    write_config(base, gear2_delay_min=1)
    taken = d.tick(MON + timedelta(minutes=2))
    assert "escalate a -> gear 2" in taken
