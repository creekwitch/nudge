"""Dataclasses for Reminder, Config, and the firing ledger."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional

APPOINTMENT = "appointment"
CHORE = "chore"
NUDGE = "nudge"
TYPES = (APPOINTMENT, CHORE, NUDGE)

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ConfigError(ValueError):
    """A reminders.yaml or config.yaml that cannot be read."""


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                pass
    raise ConfigError(f"cannot read datetime: {value!r}")


def _parse_every(value) -> int:
    """'90m' -> 90, '2h' -> 120 (minutes)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s.endswith("m") and s[:-1].isdigit():
            return int(s[:-1])
        if s.endswith("h") and s[:-1].isdigit():
            return int(s[:-1]) * 60
    raise ConfigError(f"cannot read interval: {value!r}")


@dataclass
class Reminder:
    id: str
    type: str
    text: str
    when: Optional[datetime] = None          # appointment
    schedule: Optional[str] = None           # chore: "mon,wed,fri 13:00"
    every_min: Optional[int] = None          # nudge
    active_only: bool = False
    note: str = ""
    hard: bool = False
    pair: str = ""
    gear2_min: Optional[int] = None          # per-reminder gear overrides
    gear3_min: Optional[int] = None

    @classmethod
    def from_dict(cls, raw: dict) -> "Reminder":
        if not isinstance(raw, dict):
            raise ConfigError(f"reminder entry is not a mapping: {raw!r}")
        rid = raw.get("id")
        rtype = raw.get("type")
        text = raw.get("text")
        if not rid or not isinstance(rid, str):
            raise ConfigError("reminder missing 'id'")
        if rtype not in TYPES:
            raise ConfigError(f"{rid}: unknown type {rtype!r}")
        if not text or not isinstance(text, str):
            raise ConfigError(f"{rid}: missing 'text'")
        every = _parse_every(raw["every"]) if raw.get("every") is not None else None
        schedule = raw.get("schedule")
        when = _parse_dt(raw["when"]) if raw.get("when") is not None else None
        r = cls(
            id=rid, type=rtype, text=text,
            when=when,
            schedule=schedule if isinstance(schedule, str) else None,
            every_min=every,
            active_only=bool(raw.get("active_only", False)),
            note=str(raw.get("note", "")),
            hard=bool(raw.get("hard", False)),
            pair=str(raw.get("pair", "")),
            gear2_min=raw.get("gear2_min"),
            gear3_min=raw.get("gear3_min"),
        )
        _validate_shape(r)
        return r

    def to_dict(self) -> dict:
        d = {"id": self.id, "type": self.type, "text": self.text}
        if self.when is not None:
            d["when"] = self.when.strftime("%Y-%m-%d %H:%M")
        if self.schedule is not None:
            d["schedule"] = self.schedule
        if self.every_min is not None:
            d["every"] = f"{self.every_min}m"
        if self.active_only:
            d["active_only"] = True
        if self.note:
            d["note"] = self.note
        if self.hard:
            d["hard"] = True
        if self.pair:
            d["pair"] = self.pair
        if self.gear2_min is not None:
            d["gear2_min"] = self.gear2_min
        if self.gear3_min is not None:
            d["gear3_min"] = self.gear3_min
        return d


def parse_schedule(spec: str):
    """'mon,wed,fri 13:00' -> (frozenset({'mon',...}), time(13,0)).

    Raises ConfigError on a bad shape. Lives here (not schedule.py) because
    Reminder validation needs it without a cycle.
    """
    if not isinstance(spec, str) or " " not in spec:
        raise ConfigError(f"schedule must be '<days> <HH:MM>': {spec!r}")
    parts = spec.strip().split()
    if len(parts) < 2:
        raise ConfigError(f"schedule must be '<days> <HH:MM>': {spec!r}")
    days_part, time_part = " ".join(parts[:-1]), parts[-1]
    # Accept whatever shape a human actually types: "Friday", "SUN", "wed".
    # A token is valid if it is a prefix (3+ chars) of the full English day
    # name — so "Friday", "Frid", "fri" all work, but "fribble" bounces.
    # The schedule input is free text; the parser meets people where they are.
    _FULL = {"mon": "monday", "tue": "tuesday", "wed": "wednesday",
             "thu": "thursday", "fri": "friday", "sat": "saturday",
             "sun": "sunday"}

    def _norm(tok: str) -> str:
        t = tok.strip().lower()
        if t in _FULL:
            return t
        for d, full in _FULL.items():
            if len(t) >= 3 and full.startswith(t):
                return d
        raise ConfigError(f"bad weekdays in schedule: {days_part!r}")

    days = frozenset(_norm(d) for d in days_part.split(",") if d.strip())
    if not days or not days <= set(WEEKDAYS):
        raise ConfigError(f"bad weekdays in schedule: {days_part!r}")
    try:
        hh, mm = time_part.strip().split(":")
        t = time(int(hh), int(mm))
    except (ValueError, TypeError):
        raise ConfigError(f"bad time in schedule: {time_part!r}") from None
    return days, t


def _validate_shape(r: Reminder) -> None:
    if r.type == APPOINTMENT and r.when is None:
        raise ConfigError(f"{r.id}: appointment needs 'when'")
    if r.type == CHORE:
        if not r.schedule:
            raise ConfigError(f"{r.id}: chore needs 'schedule'")
        parse_schedule(r.schedule)  # raises on bad shape
    if r.type == NUDGE and (r.every_min is None or r.every_min <= 0):
        raise ConfigError(f"{r.id}: nudge needs 'every' (e.g. 90m)")


# ---------------------------------------------------------------- config

@dataclass
class QuietHours:
    """Per-day [start, end] minute-of-day ranges; may cross midnight."""
    ranges: dict = field(default_factory=dict)  # 'mon' -> (start_min, end_min)

    @classmethod
    def from_dict(cls, raw: dict) -> "QuietHours":
        ranges = {}
        if isinstance(raw, dict):
            for day, pair in raw.items():
                day_l = str(day).lower()[:3]
                if day_l not in WEEKDAYS or not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                    raise ConfigError(f"bad quiet_hours entry for {day!r}: {pair!r}")
                ranges[day_l] = (_hhmm_to_min(pair[0], day), _hhmm_to_min(pair[1], day))
        return cls(ranges=ranges)

    def to_dict(self) -> dict:
        out = {}
        for day, (s, e) in self.ranges.items():
            out[day] = [f"{s // 60:02d}:{s % 60:02d}", f"{e // 60:02d}:{e % 60:02d}"]
        return out


def _hhmm_to_min(v, ctx) -> int:
    if isinstance(v, str) and ":" in v:
        hh, mm = v.split(":", 1)
        if hh.isdigit() and mm.isdigit() and int(hh) < 24 and int(mm) < 60:
            return int(hh) * 60 + int(mm)
    raise ConfigError(f"bad time in quiet_hours.{ctx}: {v!r}")


def default_quiet_hours() -> QuietHours:
    return QuietHours.from_dict({d: ["23:30", "09:00"] for d in WEEKDAYS})


def _clamp_volume(v) -> float:
    """Coerce a config chime_volume to 0.0..1.0.

    Accepts a fraction (0.35) or a percentage-ish int (35 meaning 35%) so a
    human editing YAML either way gets what they meant. Out-of-range or
    unparseable values clamp rather than raise: a bad volume should never
    stop the daemon, and the failure mode (a quiet chime) is harmless.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.35
    if f > 1.0:          # someone wrote 35 for 35%
        f = f / 100.0
    return max(0.0, min(1.0, f))


@dataclass
class Config:
    gear2_delay_min: int = 10
    gear3_delay_min: int = 10
    snooze_options: tuple = (5, 10, 30, 60)
    chime: bool = True
    chime_repeat_s: int = 60
    # playback volume, 0.0..1.0 (fraction of full scale). Deliberately gentle
    # by default — the chime is a care reminder, not an alarm; loud is a
    # sensory problem for the person it is caring for.
    chime_volume: float = 0.35
    popup_corner: str = "bottom-right"
    tick_seconds: int = 30
    quiet_hours: QuietHours = field(default_factory=default_quiet_hours)
    # accountability
    witness_enabled: bool = False
    witness_webhook: str = ""
    telling_enabled: bool = False
    telling_hour: int = 20
    hermes_enabled: bool = False
    hermes_hook: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        if not isinstance(raw, dict):
            raise ConfigError("config is not a mapping")
        # {} means "no quiet hours"; a missing key means "use the default"
        raw_qh = raw.get("quiet_hours")
        qh = (QuietHours.from_dict(raw_qh) if raw_qh is not None
              else default_quiet_hours())
        witness = raw.get("witness") or {}
        telling = raw.get("telling") or {}
        hermes = raw.get("hermes") or {}
        corner = raw.get("popup_corner", "bottom-right")
        if corner not in ("bottom-right", "bottom-left", "top-right", "top-left"):
            raise ConfigError(f"bad popup_corner: {corner!r}")
        return cls(
            gear2_delay_min=int(raw.get("gear2_delay_min", 10)),
            gear3_delay_min=int(raw.get("gear3_delay_min", 10)),
            snooze_options=tuple(raw.get("snooze_options", [5, 10, 30, 60])),
            chime=bool(raw.get("chime", True)),
            chime_repeat_s=int(raw.get("chime_repeat_s", 60)),
            chime_volume=_clamp_volume(raw.get("chime_volume", 0.35)),
            popup_corner=corner,
            tick_seconds=int(raw.get("tick_seconds", 30)),
            quiet_hours=qh,
            witness_enabled=bool(witness.get("enabled", False)),
            witness_webhook=str(witness.get("webhook_url", "")),
            telling_enabled=bool(telling.get("enabled", False)),
            telling_hour=int(telling.get("hour", 20)),
            hermes_enabled=bool(hermes.get("enabled", False)),
            hermes_hook=str(hermes.get("hook_path", "")),
        )
