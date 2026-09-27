"""occurrences_in_month — the calendar view's pure backend."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nudge import schedule
from nudge.models import APPOINTMENT, CHORE, NUDGE, ConfigError, Reminder


def appt(dt, **kw):
    return Reminder(id="a", type=APPOINTMENT, when=dt, text="T", **kw)


def chore(spec="mon,wed,fri 13:00", **kw):
    kw.setdefault("text", "T")
    return Reminder(id="c", type=CHORE, schedule=spec, **kw)


def nudge(every=90, **kw):
    kw.setdefault("text", "T")
    return Reminder(id="n", type=NUDGE, every_min=every, **kw)


# September 2026: 30 days, starts on a Tuesday. Oct 3 2026 is a Saturday.
def test_appointment_in_month():
    got = schedule.occurrences_in_month(appt(datetime(2026, 9, 28, 14, 0)), 2026, 9, None)
    assert got == [datetime(2026, 9, 28, 14, 0)]
    # other months: empty, not an error
    assert schedule.occurrences_in_month(appt(datetime(2026, 9, 28, 14, 0)), 2026, 10, None) == []


def test_chore_weekday_slots():
    got = schedule.occurrences_in_month(chore("mon,wed,fri 13:00"), 2026, 9, None)
    assert len(got) == 13  # Sep 2026 has 13 M/W/F days
    assert all(d.hour == 13 and d.minute == 0 for d in got)
    assert all(d.weekday() in (0, 2, 4) for d in got)
    # every occurrence in-month
    assert all(d.year == 2026 and d.month == 9 for d in got)


def test_chore_daily_spec():
    got = schedule.occurrences_in_month(chore("mon,tue,wed,thu,fri,sat,sun 8:00"), 2026, 9, None)
    assert len(got) == 30


def test_nudge_projection_from_last_fired():
    last = datetime(2026, 9, 1, 0, 0)
    got = schedule.occurrences_in_month(nudge(1440), 2026, 9, last)  # daily
    assert len(got) == 29  # fires Sep 2..30 from Sep 1 + 1d
    assert got[0] == datetime(2026, 9, 2, 0, 0)


def test_nudge_projection_absurd_cadence_capped():
    last = datetime(2026, 9, 1, 0, 0)
    got = schedule.occurrences_in_month(nudge(1), 2026, 9, last)  # every minute
    assert len(got) <= 401


def test_nudge_never_fired_far_month():
    # never fired: projections start at month start; only current-ish months project
    got = schedule.occurrences_in_month(nudge(1440), 2026, 9, None)
    assert got and got[0].day == 1
    # a past month with no anchor: nothing meaningful to show
    got = schedule.occurrences_in_month(nudge(1440), 2025, 1, None)
    assert got == []


def test_bad_schedule_still_raises():
    try:
        schedule.occurrences_in_month(chore("nonesuch 9:00"), 2026, 9, None)
        assert False
    except ConfigError:
        pass
