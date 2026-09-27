"""Pure escalation state machine: which gear applies right now."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .models import APPOINTMENT, Config, Reminder

GEAR1, GEAR2, GEAR3 = 1, 2, 3


@dataclass
class GearState:
    gear: int
    escalate_in: Optional[timedelta]  # time until next gear, None = terminal


def _delays(r: Reminder, cfg: Config) -> tuple[int, int]:
    g2 = r.gear2_min if r.gear2_min is not None else cfg.gear2_delay_min
    g3 = r.gear3_min if r.gear3_min is not None else cfg.gear3_delay_min
    return g2, g3


def gear_for(r: Reminder, fired_at: datetime, now: datetime, cfg: Config,
             snoozed_until: datetime | None = None) -> GearState:
    """Given when Gear 1 fired, what gear is this reminder in now?

    A snooze resets the clock: escalation measures from the most recent
    firing/snooze moment, so a snoozed reminder re-climbs the gears.
    """
    base = snoozed_until if (snoozed_until and snoozed_until > fired_at) else fired_at
    g2, g3 = _delays(r, cfg)
    since = (now - base).total_seconds() / 60.0
    if since >= g2 + g3:
        return GearState(GEAR3, None)
    if since >= g2:
        return GearState(GEAR2, timedelta(minutes=g2 + g3 - since))
    return GearState(GEAR1, timedelta(minutes=g2 - since))


def quiet_cap(r: Reminder, cfg: Config) -> int:
    """Max gear allowed during quiet hours. Appointments break through at
    Gear 1 only, unless hard: true (full gears). Chores/nudges never fire
    in quiet hours at all (deferred by the daemon)."""
    if r.type == APPOINTMENT and r.hard:
        return GEAR3
    if r.type == APPOINTMENT:
        return GEAR1
    return GEAR1  # chores/nudges won't fire here at all; defensive cap


def pair_ready(r: Reminder, fired_at: datetime, now: datetime, cfg: Config) -> bool:
    """Has a paired reminder survived all gears unhandled?"""
    if not r.pair:
        return False
    g2, g3 = _delays(r, cfg)
    return now >= fired_at + timedelta(minutes=g2 + g3)
