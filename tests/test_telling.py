"""The Evening Telling as scheduled daemon behavior — the wiring test."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from nudge import daemon as daemon_mod
from nudge.models import APPOINTMENT, Config, Reminder
from test_daemon import Recorder, env, write_config, write_reminders, MON  # noqa: F401

EVENING = MON.replace(hour=20, minute=0)


def seed_done_log(state_dir, rid="laundry", when=EVENING):
    line = f"{when.strftime('%Y-%m-%d')} DONE {rid}"
    (state_dir / "log").open("a").write(line + "\n")


def test_telling_fires_at_configured_hour(env):
    base, state_dir, rec = env
    write_config(base, telling_enabled=True, telling_hour=20)
    seed_done_log(state_dir)
    d = daemon_mod.Daemon(base, state_dir)
    taken = d.tick(EVENING)
    assert any("telling" in t for t in taken)
    assert d.last_told == EVENING.date().isoformat()


def test_telling_exactly_once_per_day(env):
    base, state_dir, rec = env
    write_config(base, telling_enabled=True, telling_hour=20)
    seed_done_log(state_dir)
    d = daemon_mod.Daemon(base, state_dir)
    d.tick(EVENING)
    # ticks later the same hour: silent
    assert d.tick(EVENING + timedelta(minutes=5)) == []
    assert d.tick(EVENING + timedelta(minutes=59)) == []


def test_telling_silent_other_hours(env):
    base, state_dir, rec = env
    write_config(base, telling_enabled=True, telling_hour=20)
    d = daemon_mod.Daemon(base, state_dir)
    assert d.tick(EVENING.replace(hour=19)) == []
    assert d.tick(EVENING.replace(hour=21)) == []


def test_telling_disabled_by_default(env):
    base, state_dir, rec = env
    write_config(base)  # telling_enabled defaults False
    seed_done_log(state_dir)
    d = daemon_mod.Daemon(base, state_dir)
    assert d.tick(EVENING) == []


def test_telling_empty_day_gets_kind_line(env, monkeypatch):
    base, state_dir, rec = env
    write_config(base, telling_enabled=True, telling_hour=20)
    d = daemon_mod.Daemon(base, state_dir)
    captured = {}
    import nudge.candle as candle
    monkeypatch.setattr(candle, "deliver_telling",
                        lambda cfg, report: captured.setdefault("report", report) and [])
    d.tick(EVENING)
    assert "allowed" in captured["report"] or "quiet" in captured["report"]


def test_telling_reports_todays_dones(env, monkeypatch):
    base, state_dir, rec = env
    write_config(base, telling_enabled=True, telling_hour=20)
    seed_done_log(state_dir, "laundry")
    seed_done_log(state_dir, "dishes")
    # yesterday's done must NOT appear
    seed_done_log(state_dir, "old-thing", when=EVENING - timedelta(days=1))
    d = daemon_mod.Daemon(base, state_dir)
    captured = {}
    import nudge.candle as candle
    monkeypatch.setattr(candle, "deliver_telling",
                        lambda cfg, report: captured.setdefault("report", report) and [])
    d.tick(EVENING)
    report = captured["report"]
    assert "laundry" in report and "dishes" in report
    assert "old-thing" not in report
