import os
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nudge import schedule, state as state_mod, voice
from nudge.gears import GEAR1, GEAR2, GEAR3, gear_for, pair_ready, quiet_cap
from nudge.models import (APPOINTMENT, CHORE, NUDGE, Config, ConfigError,
                          QuietHours, Reminder)

W1 = datetime(2026, 9, 28, 13, 0)   # a Monday
H = lambda d, hh=0, mm=0: W1 + __import__("datetime").timedelta(days=d, hours=hh, minutes=mm)


def appt(dt=W1.replace(hour=14, minute=0), **kw):
    return Reminder(id="t-appt", type=APPOINTMENT, when=dt, text="Dentist", **kw)


def chore(spec="mon,wed,fri 13:00", **kw):
    kw.setdefault("text", "Laundry")
    return Reminder(id="t-chore", type=CHORE, schedule=spec, **kw)


def nudge(every=90, **kw):
    kw.setdefault("text", "Stretch")
    return Reminder(id="t-nudge", type=NUDGE, every_min=every, **kw)


QH = lambda s, e, days=None: QuietHours.from_dict({d or "mon": [s, e] for d in (days or ["mon"])})


# ---------------------------------------------------------------- models

def test_every_parser():
    assert Reminder(id="x", type=NUDGE, text="t", every_min=90).every_min == 90
    r = Reminder.from_dict({"id": "x", "type": "nudge", "text": "t", "every": "2h"})
    assert r.every_min == 120


def test_bad_reminders_raise():
    for bad in (
        {"type": "chore", "text": "x"},                       # no id
        {"id": "x", "type": "party", "text": "x"},            # bad type
        {"id": "x", "type": "appointment", "text": "x"},      # no when
        {"id": "x", "type": "chore", "text": "x"},            # no schedule
        {"id": "x", "type": "chore", "text": "x", "schedule": "monnine 13:00"},
        {"id": "x", "type": "nudge", "text": "x"},            # no every
    ):
        try:
            Reminder.from_dict(bad)
            assert False, f"should raise: {bad}"
        except ConfigError:
            pass


def test_roundtrip():
    r = appt(hard=True, note="Keys.", pair="alex", gear2_min=5)
    assert Reminder.from_dict(r.to_dict()) == r


# ------------------------------------------------------- schedule day parsing

def test_schedule_accepts_full_and_cased_day_names():
    """Regression: the settings form is free text, so a person types 'Friday'.
    The parser must meet them there instead of bouncing with
    'bad weekdays in schedule: Friday'."""
    from nudge.models import parse_schedule
    days, t = parse_schedule("Friday 13:00")
    assert days == frozenset({"fri"}) and t.hour == 13
    days, _ = parse_schedule("Monday, Wednesday, Fri 8:30")
    assert days == frozenset({"mon", "wed", "fri"})
    days, _ = parse_schedule("SUN 09:00")
    assert days == frozenset({"sun"})
    # 3-letter canonical form keeps working
    assert parse_schedule("mon,wed,fri 13:00")[0] == frozenset({"mon", "wed", "fri"})


def test_schedule_time_is_last_token_not_first_space():
    """Regression: splitting on the FIRST space broke any schedule with a
    space after the comma ('Monday, Wednesday 13:00'). The time is the last
    whitespace token; everything before it is the days."""
    from nudge.models import parse_schedule
    days, t = parse_schedule("Monday, Wednesday 8:30")
    assert days == frozenset({"mon", "wed"}) and (t.hour, t.minute) == (8, 30)


def test_schedule_still_rejects_real_garbage():
    """Tolerance must not become credulity: 'Fridays' and 'fribble' are not
    weekdays, and a bare time or bare day is still a bad shape."""
    from nudge.models import parse_schedule, ConfigError as CE
    for bad in ("Fridays 13:00", "fribble 13:00", "13:00", "fri", "fri 25:00"):
        try:
            parse_schedule(bad)
            assert False, f"should raise: {bad}"
        except CE:
            pass


# ------------------------------------------------------------------- volume

def test_chime_volume_clamps_and_accepts_percent():
    """chime_volume must never raise (a bad volume shouldn't stop the daemon)
    and should read '35' as 35%, since a human editing YAML may write either."""
    from nudge.models import Config
    assert Config.from_dict({}).chime_volume == 0.35          # default
    assert Config.from_dict({"chime_volume": 0.1}).chime_volume == 0.1
    assert Config.from_dict({"chime_volume": 35}).chime_volume == 0.35
    assert Config.from_dict({"chime_volume": 0}).chime_volume == 0.0
    assert Config.from_dict({"chime_volume": 9}).chime_volume == 0.09
    assert Config.from_dict({"chime_volume": -5}).chime_volume == 0.0
    assert Config.from_dict({"chime_volume": "nonsense"}).chime_volume == 0.35


# ---------------------------------------------------------------- quiet hours

def test_quiet_basic_and_midnight():
    qh = QH("23:30", "09:00")
    assert schedule.is_quiet(qh, W1.replace(hour=8, minute=0))      # 08:00 < 09:00
    assert not schedule.is_quiet(qh, W1.replace(hour=12, minute=0))
    assert schedule.is_quiet(qh, W1.replace(hour=23, minute=45))    # after 23:30
    assert schedule.is_quiet(qh, W1.replace(hour=0, minute=30))     # past midnight, covered by mon's range
    # 00:30 Tuesday is covered by Monday's crossing range
    tue_early = datetime(2026, 9, 29, 0, 30)
    assert schedule.is_quiet(qh, tue_early)


def test_quiet_same_day_range():
    qh = QH("13:00", "15:00")
    assert schedule.is_quiet(qh, W1.replace(hour=14, minute=0))
    assert not schedule.is_quiet(qh, W1.replace(hour=16, minute=0))


def test_quiet_end():
    qh = QH("23:30", "09:00")
    late = W1.replace(hour=23, minute=45)
    end = schedule.quiet_end(qh, late)
    assert end.date() == late.date() + __import__("datetime").timedelta(days=1) and end.hour == 9
    early = W1.replace(hour=8, minute=0)
    assert schedule.quiet_end(qh, early) == early.replace(hour=9, minute=0)


# ---------------------------------------------------------------- chores

def test_chore_next_fire_week_boundary():
    r = chore("mon,wed,fri 13:00")
    # fired Friday 2026-09-25 13:00 -> next is Monday 2026-09-28 13:00
    fri = datetime(2026, 9, 25, 13, 1)
    assert schedule.next_chore_fire(r, fri) == datetime(2026, 9, 28, 13, 0)
    # before Monday's slot on Monday -> today
    mon_early = datetime(2026, 9, 28, 9, 0)
    assert schedule.next_chore_fire(r, mon_early) == datetime(2026, 9, 28, 13, 0)
    # after Monday's slot -> Wednesday
    mon_late = datetime(2026, 9, 28, 14, 0)
    assert schedule.next_chore_fire(r, mon_late) == datetime(2026, 9, 30, 13, 0)


def test_chore_due_semantics():
    r = chore()
    slot = W1.replace(second=0)
    assert not schedule.is_due(r, W1.replace(hour=12), None, None, None)      # before 13:00
    assert schedule.is_due(r, slot, None, None, None)                         # at 13:00
    assert not schedule.is_due(r, slot.replace(minute=5), slot, None, slot)   # fired this slot
    nxt = schedule.next_chore_fire(r, slot.replace(minute=10))
    assert nxt == datetime(2026, 9, 30, 13, 0)


# ---------------------------------------------------------------- nudges

def test_nudge_due():
    r = nudge(90)
    assert schedule.is_due(r, W1, None, None, None)                           # never fired
    fired = W1 - __import__("datetime").timedelta(minutes=89)
    assert not schedule.is_due(r, W1, fired, None, fired)
    fired = W1 - __import__("datetime").timedelta(minutes=91)
    assert schedule.is_due(r, W1, fired, None, fired)


def test_snooze_blocks_then_releases():
    r = nudge(90)
    snoozed_until = W1 + __import__("datetime").timedelta(minutes=10)
    assert not schedule.is_due(r, W1 + __import__("datetime").timedelta(minutes=5), None, snoozed_until, None)
    assert schedule.is_due(r, snoozed_until, None, snoozed_until, None)


# ---------------------------------------------------------------- gears

def test_gear_escalation():
    cfg = Config()
    fired = W1.replace(hour=14, minute=0)
    assert gear_for(appt(), fired, fired + __import__("datetime").timedelta(minutes=9), cfg).gear == GEAR1
    assert gear_for(appt(), fired, fired + __import__("datetime").timedelta(minutes=10), cfg).gear == GEAR2
    assert gear_for(appt(), fired, fired + __import__("datetime").timedelta(minutes=20), cfg).gear == GEAR3


def test_gear_per_reminder_override():
    cfg = Config()
    r = appt(gear2_min=1, gear3_min=1)
    fired = W1.replace(hour=14, minute=0)
    assert gear_for(r, fired, fired + __import__("datetime").timedelta(minutes=2), cfg).gear == GEAR3


def test_snooze_resets_gear_clock():
    cfg = Config()
    r = appt()
    fired = W1.replace(hour=14, minute=0)
    snoozed = fired + __import__("datetime").timedelta(minutes=25)
    # 5 minutes after the snooze began: back to Gear 1, not Gear 3
    assert gear_for(r, fired, snoozed + __import__("datetime").timedelta(minutes=5), cfg, snoozed).gear == GEAR1


def test_quiet_cap():
    assert quiet_cap(appt(), Config()) == GEAR1
    assert quiet_cap(appt(hard=True), Config()) == GEAR3


def test_pair_ready():
    cfg = Config()
    r = appt(pair="alex")
    fired = W1.replace(hour=14, minute=0)
    assert not pair_ready(r, fired, fired + __import__("datetime").timedelta(minutes=19), cfg)
    assert pair_ready(r, fired, fired + __import__("datetime").timedelta(minutes=20), cfg)
    assert not pair_ready(appt(), fired, fired + __import__("datetime").timedelta(hours=5), cfg)


# ---------------------------------------------------------------- voice

def test_voice_never_repeats_consecutively():
    import random
    rng = random.Random(7)
    seen_last = None
    for _ in range(200):
        p = voice.pick(voice.FIRE, seen_last, rng)
        assert p != seen_last
        seen_last = p


def test_voice_render_weaves_note():
    out = voice.render(voice.FIRE, "Laundry", "check pockets", rng=random.Random(1))
    assert "Laundry" in out and "check pockets" in out


# ---------------------------------------------------------------- ledger

def test_ledger_fire_ack_snooze():
    led = {}
    led = state_mod.register_fire(led, "x", W1, "phrase one")
    e = state_mod.entry(led, "x")
    assert e["gear"] == 1 and e["last_phrase"] == "phrase one"
    led = state_mod.snooze(led, "x", W1 + __import__("datetime").timedelta(minutes=10), W1)
    assert state_mod.entry(led, "x")["gear"] == 0
    led = state_mod.acknowledge(led, "x", state_mod.DONE, H(0, 14, 30))
    e = state_mod.entry(led, "x")
    assert e["verdict"] == "done" and e["gear"] == 0 and e["snoozed_until"] is None
    # original dict untouched (copy-on-write)
    assert state_mod.entry({}, "x")["gear"] == 0


def test_ledger_phrase_varies():
    import random
    rng = random.Random(3)
    led, last = {}, None
    for _ in range(50):
        p = voice.pick(voice.FIRE2, last, rng)
        assert p != last
        led = state_mod.register_fire(led, "x", W1, p)
        last = state_mod.entry(led, "x")["last_phrase"]
