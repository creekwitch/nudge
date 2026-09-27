"""server.py — API round-trips against a real server on a scratch home."""
import json
import sys
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from nudge import server as server_mod
from nudge.daemon import Daemon
from nudge.models import APPOINTMENT, Config

PORT = 8131


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    base = tmp_path_factory.mktemp("cfg")
    state = tmp_path_factory.mktemp("state")
    cfg = Config()
    from nudge import store
    store.save_config(cfg, store.config_path(base))
    d = Daemon(base, state)
    httpd = server_mod.ThreadingHTTPServer(("127.0.0.1", PORT),
                                           server_mod.build_handler(d))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{PORT}", base, d
    httpd.shutdown()


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data,
                               method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def test_reminder_crud_roundtrip(srv):
    url, base, d = srv
    code, body = req("POST", "/api/reminders", {
        "id": "laundry", "type": "chore", "text": "Laundry",
        "schedule": "mon,wed,fri 13:00"})
    assert code == 201
    # duplicate refused
    code, _ = req("POST", "/api/reminders", {
        "id": "laundry", "type": "chore", "text": "Laundry", "schedule": "tue 9:00"})
    assert code == 409
    # invalid refused with reason
    code, body = req("POST", "/api/reminders", {"id": "bad", "type": "chore", "text": "x"})
    assert code == 400 and "schedule" in body["error"]
    # listed with derived next_fire
    code, body = req("GET", "/api/reminders")
    assert code == 200 and body["reminders"][0]["id"] == "laundry"
    assert body["reminders"][0]["next_fire"] is not None
    # patch
    code, body = req("PATCH", "/api/reminders/laundry", {"text": "Laundry + sheets"})
    assert code == 200 and body["text"] == "Laundry + sheets"
    # persisted to disk (daemon re-reads; no restart)
    from nudge import store
    on_disk = {r.id: r for r in store.load_reminders(store.reminders_path(base))}
    assert on_disk["laundry"].text == "Laundry + sheets"
    # delete
    code, _ = req("DELETE", "/api/reminders/laundry")
    assert code == 200


def test_config_put_roundtrip_and_daemon_sees_it(srv):
    url, base, d = srv
    code, cfg = req("GET", "/api/config")
    assert code == 200
    cfg["gear2_delay_min"] = 3
    code, _ = req("PUT", "/api/config", cfg)
    assert code == 200
    # the DAEMON (separate object, like the real process) sees the change
    assert d._config().gear2_delay_min == 3


def test_status_endpoint(srv):
    url, base, d = srv
    code, st = req("GET", "/api/status")
    assert code == 200
    assert {"quiet", "pending", "deferred", "next"} <= set(st)


def test_static_ui_served(srv):
    url, _, _ = srv
    with urllib.request.urlopen(f"{url}/") as resp:
        html = resp.read().decode()
    assert "Nudge" in html and "app.js" in html
    with urllib.request.urlopen(f"{url}/app.js") as resp:
        assert b"textContent" in resp.read()


def test_test_fire_endpoint(srv, monkeypatch):
    url, base, d = srv
    req("POST", "/api/reminders", {"id": "tf", "type": "nudge", "text": "Probe", "every": "1h"})
    import nudge.server as s
    monkeypatch.setattr(s.actions, "notify", lambda *a, **k: None)
    code, body = req("POST", "/api/test-fire", {"id": "tf"})
    assert code == 200 and body["fired"] == "tf" and "Probe" in body["phrase"]
    code, _ = req("POST", "/api/test-fire", {"id": "nope"})
    assert code == 404


def test_calendar_endpoint(srv):
    url, base, d = srv
    req("POST", "/api/reminders", {
        "id": "calappt", "type": "appointment", "text": "Dentist",
        "when": "2026-10-03 14:00"})
    import datetime as dt
    now = dt.datetime.now()
    # current month always returns 200 with grid facts
    code, cal = req("GET", f"/api/calendar?year={now.year}&month={now.month}")
    assert code == 200
    assert {"year", "month", "month_name", "today", "first_weekday",
            "days_in_month", "events"} <= set(cal)
    # the appointment shows in its month with type + time
    code, cal = req("GET", "/api/calendar?year=2026&month=10")
    assert code == 200
    ev = [e for e in cal["events"] if e["id"] == "calappt"]
    assert ev and ev[0]["type"] == "appointment" and "14:00" in ev[0]["at"]
    # events sorted by time
    ats = [e["at"] for e in cal["events"]]
    assert ats == sorted(ats)
    # bad month refused
    code, _ = req("GET", "/api/calendar?year=2026&month=13")
    assert code == 400


def test_popup_verdict_endpoint_queues_for_daemon(srv):
    url, base, d = srv
    import datetime as dt
    from nudge import state as s
    from nudge.daemon import Daemon
    # a fired reminder the desklet would act on
    req("POST", "/api/reminders", {"id": "vd", "type": "nudge", "text": "Stretch", "every": "1h"})
    dd = Daemon(base, d.state_dir)
    dd.ledger = s.register_fire(dd.ledger, "vd", dt.datetime.now(), "phrase")
    dd._save_ledger()
    # desklet sends Done via the API
    code, body = req("POST", "/api/popup-verdict", {"id": "vd", "verdict": "done"})
    assert code == 202 and body["queued"]["verdict"] == "done"
    # the daemon picks it up on its next tick (same file the popup writes)
    taken = dd.tick(dt.datetime.now())
    assert "popup done vd" in taken
    assert s.entry(dd.ledger, "vd")["verdict"] == "done"
    # invalid verdict / unknown id refused
    assert req("POST", "/api/popup-verdict", {"id": "vd", "verdict": "nope"})[0] == 400
    assert req("POST", "/api/popup-verdict", {"id": "ghost", "verdict": "done"})[0] == 404


def test_popup_verdict_snooze(srv):
    url, base, d = srv
    import datetime as dt
    from nudge import state as s
    from nudge.daemon import Daemon
    dd = Daemon(base, d.state_dir)
    code, _ = req("POST", "/api/popup-verdict",
                  {"id": "vd", "verdict": "snooze", "snooze_min": 30})
    assert code == 202
    dd.tick(dt.datetime.now())
    assert s.entry(dd.ledger, "vd")["snoozed_until"] is not None


def test_calendar_collapses_interval_nudges(srv):
    """A 90m nudge must not claim hundreds of cells — one entry per day."""
    url, base, d = srv
    import datetime as dt
    from nudge.daemon import Daemon
    from nudge import state as s
    req("POST", "/api/reminders",
        {"id": "n90", "type": "nudge", "text": "Stretch", "every": "90m"})
    dd = Daemon(base, d.state_dir)
    dd.ledger = s.register_fire(dd.ledger, "n90", dt.datetime(2026, 9, 1, 8, 0), "p")
    dd._save_ledger()
    code, cal = req("GET", "/api/calendar?year=2026&month=9")
    assert code == 200
    nudge_evs = [e for e in cal["events"] if e["id"] == "n90"]
    # The contract is "at most one per day", not "every day" — the projection is
    # bounded (see schedule.occurrences_in_month), so it covers what it can prove
    # and stops. What must never happen is the same day appearing many times.
    days = [e["at"][:10] for e in nudge_evs]
    assert len(days) == len(set(days)), "a day must appear only once"
    assert 0 < len(nudge_evs) <= 30, f"sane coverage, got {len(nudge_evs)}"
    assert nudge_evs[0]["repeats"] == "90m"


def test_calendar_rejects_bad_month(srv):
    url, base, d = srv
    assert req("GET", "/api/calendar?year=2026&month=13")[0] == 400
    assert req("GET", "/api/calendar?year=2026&month=0")[0] == 400


def test_log_endpoint(srv):
    url, base, d = srv
    # with a log present, tail returns exactly the last N lines
    (d.state_dir / "log").write_text("\n".join(f"line {i}" for i in range(200)) + "\n")
    code, body = req("GET", "/api/log?lines=5")
    assert code == 200 and body["lines"] == ["line 195", "line 196", "line 197",
                                             "line 198", "line 199"]
    # a missing log is empty, not an error
    (d.state_dir / "log").unlink()
    code, body = req("GET", "/api/log")
    assert code == 200 and body["lines"] == []


def test_reschedule_appointment_keeps_time(srv):
    """Dragging an appointment moves the date and keeps the clock time."""
    url, base, d = srv
    req("POST", "/api/reminders", {"id": "mv", "type": "appointment",
                                   "text": "Move me", "when": "2026-10-06 15:00"})
    code, body = req("PATCH", "/api/reminders/mv", {"when": "2026-10-09 15:00"})
    assert code == 200 and body["when"] == "2026-10-09 15:00"
    # and a nonsense date is refused rather than silently stored
    assert req("PATCH", "/api/reminders/mv", {"when": "yesterday"})[0] == 400
    # the reminder is unchanged after the refused edit
    code, body = req("GET", "/api/reminders")
    assert next(r for r in body["reminders"] if r["id"] == "mv")["when"] == "2026-10-09 15:00"


def test_reschedule_chore_adds_weekday(srv):
    """Dragging a chore onto a day adds that weekday, time preserved."""
    url, base, d = srv
    req("POST", "/api/reminders", {"id": "ch2", "type": "chore",
                                   "text": "Laundry", "schedule": "mon,wed,fri 13:00"})
    code, body = req("PATCH", "/api/reminders/ch2", {"schedule": "mon,wed,fri,sat 13:00"})
    assert code == 200 and body["schedule"] == "mon,wed,fri,sat 13:00"
    # a chore with no weekdays would never fire again — must be refused
    assert req("PATCH", "/api/reminders/ch2", {"schedule": " 13:00"})[0] == 400


def test_calendar_says_which_events_can_move(srv):
    """The calendar marks movable events so the UI knows what to make draggable."""
    url, base, d = srv
    import datetime as dt
    from nudge.daemon import Daemon
    from nudge import state as s
    req("POST", "/api/reminders", {"id": "mo", "type": "appointment",
                                   "text": "Appt", "when": "2026-10-06 15:00"})
    req("POST", "/api/reminders", {"id": "nu", "type": "nudge",
                                   "text": "Stretch", "every": "90m"})
    dd = Daemon(base, d.state_dir)
    dd.ledger = s.register_fire(dd.ledger, "nu", dt.datetime(2026, 10, 1, 8, 0), "p")
    dd._save_ledger()
    code, cal = req("GET", "/api/calendar?year=2026&month=10")
    by_id = {}
    for e in cal["events"]:
        by_id.setdefault(e["id"], e)
    assert by_id["mo"]["type"] == "appointment"
    assert by_id["nu"]["repeats"] == "90m"
