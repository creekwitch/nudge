"""Firing ledger logic — pure operations over a plain dict.

The ledger is facts, not logic (AGENTS.md). Shape:
    {reminder_id: {
        "last_fired": iso8601 | None,     # last Gear-1 fire
        "gear": int,                      # current gear
        "gear_entered": iso8601 | None,   # when current gear began
        "snoozed_until": iso8601 | None,
        "verdict": "done"|"didnt"|None,   # last acknowledgment
        "verdict_at": iso8601 | None,
        "last_phrase": str | None,
        "deferred": bool,                 # parked by quiet hours
        "pair_sent": iso8601 | None,      # pair nudge already sent for this cycle
    }}
"""
from __future__ import annotations

from datetime import datetime

DONE = "done"
DIDNT = "didnt"

BLANK = {
    "last_fired": None, "gear": 0, "gear_entered": None,
    "snoozed_until": None, "verdict": None, "verdict_at": None,
    "last_phrase": None, "deferred": False, "pair_sent": None,
}


def entry(ledger: dict, rid: str) -> dict:
    e = dict(BLANK)
    e.update(ledger.get(rid) or {})
    return e


def register_fire(ledger: dict, rid: str, now: datetime, phrase: str) -> dict:
    """Copy-on-write: returns the NEW ledger with the fire recorded."""
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in ledger.items()}
    e = entry(out, rid)
    e.update(last_fired=now.isoformat(), gear=1, gear_entered=now.isoformat(),
             snoozed_until=None, verdict=None, verdict_at=None,
             last_phrase=phrase, deferred=False, pair_sent=None)
    out[rid] = e
    return out


def set_gear(ledger: dict, rid: str, gear: int, now: datetime) -> dict:
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in ledger.items()}
    e = entry(out, rid)
    if e["gear"] != gear:
        e["gear"] = gear
        e["gear_entered"] = now.isoformat()
    out[rid] = e
    return out


def snooze(ledger: dict, rid: str, until: datetime, now: datetime) -> dict:
    """A snooze re-arms the reminder at Gear 1 when `until` arrives."""
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in ledger.items()}
    e = entry(out, rid)
    e.update(snoozed_until=until.isoformat(), gear=0, gear_entered=None,
             verdict=None, verdict_at=None)
    out[rid] = e
    return out


def acknowledge(ledger: dict, rid: str, verdict: str, now: datetime) -> dict:
    """Done or Didn't — closes the firing cycle."""
    assert verdict in (DONE, DIDNT)
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in ledger.items()}
    e = entry(out, rid)
    e.update(verdict=verdict, verdict_at=now.isoformat(), gear=0,
             gear_entered=None, snoozed_until=None, deferred=False)
    out[rid] = e
    return out


def defer(ledger: dict, rid: str, now: datetime) -> dict:
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in ledger.items()}
    e = entry(out, rid)
    e["deferred"] = True
    out[rid] = e
    return out


def mark_pair_sent(ledger: dict, rid: str, now: datetime) -> dict:
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in ledger.items()}
    e = entry(out, rid)
    e["pair_sent"] = now.isoformat()
    out[rid] = e
    return out


def parse_ts(iso: str | None) -> datetime | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso)
