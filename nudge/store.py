"""The ONLY module that reads/writes YAML and the ledger file (AGENTS.md).

Atomic writes (tmp + rename); load errors raise ConfigError loudly.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import yaml

from .models import Config, ConfigError, Reminder
from . import state as state_mod

DEFAULT_DIR = Path(os.environ.get("NUDGE_HOME", Path.home() / ".config" / "nudge"))
DEFAULT_STATE_DIR = Path(os.environ.get("NUDGE_STATE", Path.home() / ".local" / "state" / "nudge"))


def reminders_path(base: Path | None = None) -> Path:
    return (base or DEFAULT_DIR) / "reminders.yaml"


def config_path(base: Path | None = None) -> Path:
    return (base or DEFAULT_DIR) / "config.yaml"


def ledger_path(base: Path | None = None) -> Path:
    return (base or DEFAULT_STATE_DIR) / "ledger.json"


def load_reminders(path: Path) -> list[Reminder]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or {}
    entries = raw.get("reminders", [])
    if not isinstance(entries, list):
        raise ConfigError("reminders.yaml: 'reminders' must be a list")
    out, seen = [], set()
    for e in entries:
        r = Reminder.from_dict(e)
        if r.id in seen:
            raise ConfigError(f"duplicate reminder id: {r.id}")
        seen.add(r.id)
        out.append(r)
    return out


def save_reminders(reminders: list[Reminder], path: Path) -> None:
    doc = {"reminders": [r.to_dict() for r in reminders]}
    _atomic_write(path, yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    return Config.from_dict(yaml.safe_load(path.read_text()) or {})


def save_config(cfg: Config, path: Path) -> None:
    doc = {
        "gear2_delay_min": cfg.gear2_delay_min,
        "gear3_delay_min": cfg.gear3_delay_min,
        "snooze_options": list(cfg.snooze_options),
        "chime": cfg.chime,
        "chime_repeat_s": cfg.chime_repeat_s,
        "popup_corner": cfg.popup_corner,
        "tick_seconds": cfg.tick_seconds,
        "quiet_hours": cfg.quiet_hours.to_dict(),
        "witness": {"enabled": cfg.witness_enabled, "webhook_url": cfg.witness_webhook},
        "telling": {"enabled": cfg.telling_enabled, "hour": cfg.telling_hour},
        "hermes": {"enabled": cfg.hermes_enabled, "hook_path": cfg.hermes_hook},
    }
    _atomic_write(path, yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    try:
        os.chmod(path, 0o600)  # webhook secrets may live here
    except OSError:
        pass


def load_ledger(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text()) or {}
    except json.JSONDecodeError as e:
        raise ConfigError(f"ledger corrupt ({e}); move it aside and restart") from None


def save_ledger(ledger: dict, path: Path) -> None:
    _atomic_write(path, json.dumps(ledger, indent=1, sort_keys=True))


LOG_MAX_BYTES = 512 * 1024   # half a megabyte ≈ a year of ordinary use


def append_log(path: Path, line: str, now_stamp: str) -> None:
    """Append one line, trimming the oldest lines when the file gets long.

    This daemon is meant to run for months, and the log is read by `nudge log`
    and by the Status panel — both want the tail, neither wants a file that
    grows without bound. Trimming keeps the newest half when the cap is passed,
    which is the part the tuning actually reads.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(f"{now_stamp} {line}\n")
    try:
        if path.stat().st_size > LOG_MAX_BYTES:
            _trim_log(path)
    except OSError:
        pass   # a log that can't be trimmed is still a log; never crash the tick


def _trim_log(path: Path) -> None:
    text = path.read_text(errors="replace")
    # keep the newer half, and start on a line boundary
    lines = text.splitlines()
    keep = lines[len(lines) // 2:]
    _atomic_write(path, "\n".join(keep) + "\n")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".nudge-tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


__all__ = ["state_mod"]
