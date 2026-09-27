"""Pure schedule math: what fires, when, and is it quiet.

Every function takes an explicit `now`. This module is the ONLY place
recurrence and quiet-hour questions are answered (AGENTS.md).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .models import (APPOINTMENT, CHORE, NUDGE, WEEKDAYS, ConfigError,
                     Reminder, parse_schedule)

DAY_NAMES = {d: i for i, d in enumerate(WEEKDAYS)}  # mon=0 ... sun=6


def _minute_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def is_quiet(qh, now: datetime) -> bool:
    """Quiet-hours check; ranges may cross midnight."""
    day = WEEKDAYS[now.weekday()]
    m = _minute_of_day(now)
    rng = qh.ranges.get(day)
    if rng:
        s, e = rng
        if s <= e:
            if s <= m < e:
                return True
        else:  # crosses midnight: e.g. 23:30 -> 09:00
            if m >= s or m < e:
                return True
    # a range from *yesterday* may still cover just after midnight
    prev = WEEKDAYS[(now.weekday() - 1) % 7]
    rng = qh.ranges.get(prev)
    if rng:
        s, e = rng
        if s > e and m < e:  # previous day's range crossing into today
            return True
    return False


def quiet_end(qh, now: datetime) -> datetime:
    """The moment quiet hours next end, for deferred delivery.

    Assumes `is_quiet(qh, now)` is True.
    """
    day = WEEKDAYS[now.weekday()]
    m = _minute_of_day(now)
    base = now.replace(second=0, microsecond=0)
    rng = qh.ranges.get(day)
    if rng:
        s, e = rng
        crossing = s > e
        if (s <= e and s <= m < e) or (crossing and (m >= s or m < e)):
            # ends today at e; a crossing range whose end has passed
            # relative to m (m >= s, late evening) ends calendar tomorrow
            end_today = base.replace(hour=e // 60, minute=e % 60)
            if crossing and m >= s and e <= m:
                end_today += timedelta(days=1)
            if end_today > now:
                return end_today
            # late-night edge: end already passed today means tomorrow
            return end_today + timedelta(days=1)
    # must be covered by yesterday's crossing range
    prev = WEEKDAYS[(now.weekday() - 1) % 7]
    rng = qh.ranges.get(prev)
    if rng and rng[0] > rng[1]:  # crossing range from yesterday covers now
        end = base.replace(hour=rng[1] // 60, minute=rng[1] % 60)
        if end <= now:
            end += timedelta(days=1)
        return end
    # defensive fallback: one minute past now
    return base + timedelta(minutes=1)


def parse_when_appointment(r: Reminder):
    return r.when


def next_chore_fire(r: Reminder, after: datetime) -> datetime:
    """Next occurrence of a chore strictly after `after`."""
    days, t = parse_schedule(r.schedule)
    candidate = after.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    for _ in range(8):
        if candidate > after and WEEKDAYS[candidate.weekday()] in days:
            return candidate
        candidate += timedelta(days=1)
    raise ConfigError(f"{r.id}: schedule never fires? {r.schedule!r}")


def next_nudge_fire(r: Reminder, after: datetime, last_fired: datetime | None) -> datetime:
    """Next nudge fire = last fire + interval (or now if never fired)."""
    if last_fired is None:
        return after
    return last_fired + timedelta(minutes=r.every_min)


def next_fire(r: Reminder, after: datetime, last_fired: datetime | None = None) -> datetime | None:
    """THE one definition of 'due'. Returns when this reminder next fires,
    or None for an appointment already in the past."""
    if r.type == APPOINTMENT:
        return r.when if (r.when and r.when > after) else (r.when if r.when and after <= r.when else (r.when if r.when > after else None))
    if r.type == CHORE:
        return next_chore_fire(r, after)
    if r.type == NUDGE:
        return next_nudge_fire(r, after, last_fired)
    return None


def is_due(r: Reminder, now: datetime, last_fired: datetime | None,
           snoozed_until: datetime | None, fired_at: datetime | None) -> bool:
    """Should this reminder fire its Gear 1 right now?"""
    if snoozed_until and now < snoozed_until:
        return False
    if r.type == APPOINTMENT:
        # fires once at its time: due if now >= when and not fired since
        if r.when is None:
            return False
        if fired_at is not None and fired_at >= r.when:
            return False
        return now >= r.when
    if r.type == CHORE:
        days, t = parse_schedule(r.schedule)
        if WEEKDAYS[now.weekday()] not in days:
            return False
        slot = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if now < slot:
            return False
        # due if not yet fired for this occurrence
        if fired_at is not None and fired_at >= slot:
            return False
        return True
    if r.type == NUDGE:
        if snoozed_until and now >= snoozed_until:
            return True  # the snooze was the reschedule; expired means due
        base = last_fired or (fired_at or None)
        if base is None:
            return True
        return now >= base + timedelta(minutes=r.every_min)
    return False


def occurrences_in_month(r: Reminder, year: int, month: int,
                         last_fired: datetime | None) -> list[datetime]:
    """Scheduled fires for one reminder in a calendar month (pure, for the
    UI's calendar view — the ONE second reader of next_fire math, living
    beside it so they cannot disagree).

    - appointment: its `when`, if in this month
    - chore: every weekday-slot in the month
    - nudge: projections from last_fired (or month start) at interval steps;
      projections are estimates and only meaningful while they precede
      "now + one interval" — beyond that they're a steady cadence.
    """
    import calendar as cal_mod
    days_in_month = cal_mod.monthrange(year, month)[1]
    out: list[datetime] = []
    if r.type == APPOINTMENT:
        if r.when and r.when.year == year and r.when.month == month:
            out.append(r.when)
        return out
    if r.type == CHORE:
        days, t = parse_schedule(r.schedule)
        for day in range(1, days_in_month + 1):
            d = datetime(year, month, day, t.hour, t.minute)
            if WEEKDAYS[d.weekday()] in days:
                out.append(d)
        return out
    if r.type == NUDGE:
        step = timedelta(minutes=r.every_min)
        month_start = datetime(year, month, 1)
        month_end = datetime(year, month, days_in_month, 23, 59)
        if not last_fired:
            # no anchor: project from the month's start only if the month is
            # current or future (a past month with no history is meaningless)
            if month_end < datetime.now():
                return []
            nxt = month_start
        else:
            nxt = last_fired + step
            while nxt < month_start:
                nxt += step
            if nxt > month_end and last_fired < month_start:
                return []  # anchored before the month but next fire is beyond it
        while nxt <= month_end:
            out.append(nxt)
            nxt += step
            if len(out) > 400:  # absurd cadence guard (every: 1m over months)
                break
        return out
    return out
