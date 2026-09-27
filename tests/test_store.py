"""store.py: atomic YAML/ledger round-trips (scratch dirs, never real config)."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from nudge import store
from nudge.models import APPOINTMENT, CHORE, Config, ConfigError, Reminder


@pytest.fixture
def home(tmp_path):
    return tmp_path


def test_reminders_roundtrip(home):
    p = store.reminders_path(home)
    rs = [
        Reminder(id="appt", type=APPOINTMENT, when=datetime(2026, 10, 3, 14, 0),
                 text="Dentist", note="Keys.", hard=True),
        Reminder(id="ch", type=CHORE, schedule="mon,wed,fri 13:00", text="Laundry"),
    ]
    store.save_reminders(rs, p)
    back = store.load_reminders(p)
    assert back == rs
    # written YAML is zero-padded + readable (the YAML-times pitfall)
    assert '"when"' not in p.read_text() or "2026-10-03 14:00" in p.read_text()


def test_config_roundtrip_and_0600(home):
    p = store.config_path(home)
    cfg = Config(witness_enabled=True, witness_webhook="https://discord.example/hook")
    store.save_config(cfg, p)
    assert store.load_config(p) == cfg
    assert (p.stat().st_mode & 0o777) == 0o600


def test_bad_config_raises_loudly(home):
    p = store.config_path(home)
    p.write_text("popup_corner: sideways\n")
    with pytest.raises(ConfigError):
        store.load_config(p)
    p2 = store.reminders_path(home)
    p2.write_text("reminders: {not: a list}\n")
    with pytest.raises(ConfigError):
        store.load_reminders(p2)


def test_ledger_roundtrip_and_corruption(home):
    p = store.ledger_path(home)
    led = {"x": {"last_fired": "2026-09-28T13:00:00", "gear": 2}}
    store.save_ledger(led, p)
    assert store.load_ledger(p) == led
    p.write_text("{not json")
    with pytest.raises(ConfigError):
        store.load_ledger(p)


def test_atomic_write_leaves_no_tmp(home):
    p = home / "sub" / "f.yaml"
    store.save_reminders([], p)
    assert list((home / "sub").glob(".nudge-tmp*")) == []


def test_log_is_capped(tmp_path):
    """A daemon meant to run for months must not grow an unbounded log."""
    from nudge import store
    logp = tmp_path / "log"
    # write well past the cap
    for i in range(20000):
        store.append_log(logp, f"line {i}", "2026-01-01 00:00")
    size = logp.stat().st_size
    assert size <= store.LOG_MAX_BYTES * 1.2, f"log ran away: {size}"
    lines = logp.read_text().splitlines()
    # the newest line survives — that is what tuning reads
    assert lines[-1].endswith("line 19999")
    # and no line was cut in half
    assert all(l.startswith("2026-01-01 00:00 line ") for l in lines)


def test_log_cap_keeps_recent_and_stays_parseable(tmp_path):
    from nudge import store
    logp = tmp_path / "log"
    for i in range(20000):
        store.append_log(logp, f"e{i}", "2026-01-01 00:00")
    lines = logp.read_text().splitlines()
    assert len(lines) > 100, "trimming threw away too much"
    assert lines == sorted(lines, key=lambda l: int(l.rsplit("e", 1)[1])), "order preserved"
