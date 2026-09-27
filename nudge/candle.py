"""The Witness (Discord candles), Pair pings, and the Evening Telling.

Outbound integration is ONLY: the configured Discord webhook and the
configured Hermes hook (SPEC constitution #4). urllib, no deps.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime


def _post_json(url: str, payload: dict, timeout: int = 10) -> bool:
    if not url:
        return False
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return False
    return ok


def candle_line(rid: str, when: datetime) -> str:
    """One line, no commentary, no score."""
    return f"🕯️ {rid} — done, {when.strftime('%a %I:%M%p').lstrip('0')}"


def send_candle(cfg, rid: str, when: datetime) -> bool:
    """The Witness: lights a candle in the configured channel. Returns
    False on any failure so the daemon keeps it queued (never dropped)."""
    return _post_json(cfg.witness_webhook, {"content": candle_line(rid, when)})


def send_pair_ping(cfg, r) -> bool:
    """The Pair Nudge — she opted in per-reminder; a gentle word, not an alarm."""
    from . import voice
    msg = voice.pick(voice.PAIR_LINES).format(text=r.text)
    return _post_json(cfg.witness_webhook, {"content": f"**{r.pair}** — {msg}"})


def drain_candles(cfg, queue: list[str]) -> int:
    """Try to send queued candles IN ORDER; keep the ones that failed."""
    if not queue:
        return 0
    sent = 0
    remaining = []
    for i, line in enumerate(queue):
        if i > 0 and not cfg.witness_webhook:
            remaining.extend(queue[i:])   # order-preserving stop on no-webhook
            break
        if _post_json(cfg.witness_webhook, {"content": line}):
            sent += 1
        else:
            remaining.extend(queue[i:])   # this one failed; stop in order
            break
    queue[:] = remaining
    return sent


def hearth_report(dones: list[str], day) -> str:
    """The Evening Telling: the day's Dones told back, warmly."""
    from . import voice
    if not dones:
        opener = voice.pick(voice.TELLING_EMPTY)
        return opener
    opener = voice.pick(voice.TELLING_OPENERS)
    lines = "\n".join(f"  🕯️ {d}" for d in dones)
    return f"{opener}\n{lines}"


def deliver_telling(cfg, report: str) -> list[str]:
    """Deliver via Hermes hook (file drop for the agent) + optional Discord."""
    out = []
    if cfg.hermes_enabled and cfg.hermes_hook:
        try:
            path = cfg.hermes_hook
            with open(path, "a") as f:
                f.write(f"\n[nudge telling {datetime.now().isoformat(timespec='minutes')}]\n{report}\n")
            out.append("hermes")
        except OSError:
            pass
    if cfg.witness_enabled and cfg.witness_webhook:
        if _post_json(cfg.witness_webhook, {"content": report}):
            out.append("discord")
    return out
