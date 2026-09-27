"""candle.py — outbound accountability, tested against a local HTTP server."""
import json
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from nudge import candle
from nudge.models import APPOINTMENT, Config, Reminder


class Hook(BaseHTTPRequestHandler):
    received = []
    fail_next = False

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).received.append(json.loads(body))
        if type(self).fail_next:
            self.send_response(500)
            self.end_headers()
            type(self).fail_next = False
        else:
            self.send_response(204)
            self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Hook)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    Hook.received.clear()
    Hook.fail_next = False
    yield f"http://127.0.0.1:{httpd.server_port}", Hook
    httpd.shutdown()


def test_candle_line_has_no_commentary():
    line = candle.candle_line("laundry", datetime(2026, 9, 25, 14, 14))
    assert line.startswith("🕯️ laundry — done, Fri 02:14PM")
    assert "good" not in line.lower() and "great" not in line.lower()  # no score


def test_send_candle_posts(server):
    url, Hook = server
    cfg = Config(witness_enabled=True, witness_webhook=url)
    assert candle.send_candle(cfg, "laundry", datetime(2026, 9, 25, 14, 14))
    assert Hook.received and "laundry" in Hook.received[0]["content"]


def test_failed_webhook_returns_false(server):
    url, Hook = server
    cfg = Config(witness_enabled=True, witness_webhook=url)
    Hook.fail_next = True
    assert candle.send_candle(cfg, "x", datetime.now()) is False


def test_drain_keeps_failed_candles_queued(server):
    url, Hook = server
    cfg = Config(witness_enabled=True, witness_webhook=url)
    Hook.fail_next = True
    queue = ["candle one", "candle two"]
    # first fails -> nothing sent, BOTH stay (in-order: never skip past a failure)
    assert candle.drain_candles(cfg, queue) == 0
    assert queue == ["candle one", "candle two"]
    # webhook recovers -> both drain in order
    assert candle.drain_candles(cfg, queue) == 2
    assert queue == []


def test_no_webhook_means_no_send_but_no_crash():
    cfg = Config()
    queue = ["a candle"]
    assert candle.drain_candles(cfg, queue) == 0
    assert queue == ["a candle"]


def test_pair_ping_names_the_person(server):
    url, Hook = server
    cfg = Config(witness_enabled=True, witness_webhook=url)
    r = Reminder(id="meds", type=APPOINTMENT, when=datetime(2026, 10, 1, 9, 0),
                 text="Meds", pair="alex")
    candle.send_pair_ping(cfg, r)
    assert Hook.received and Hook.received[0]["content"].startswith("**alex**")


def test_hearth_report_empty_day_is_kind():
    rep = candle.hearth_report([], None)
    assert "allowed" in rep or "quiet" in rep  # no judgment either way


def test_hearth_report_lists_dones():
    rep = candle.hearth_report(["laundry", "dishes"], None)
    assert "laundry" in rep and "dishes" in rep


def test_telling_delivers_to_hermes_hook(tmp_path, server):
    url, _ = server
    hook = tmp_path / "hermes-feed.md"
    cfg = Config(witness_enabled=True, witness_webhook=url,
                 hermes_enabled=True, hermes_hook=str(hook))
    out = candle.deliver_telling(cfg, "The hearth report:\n  🕯️ laundry")
    assert "hermes" in out and "discord" in out
    assert "laundry" in hook.read_text()
