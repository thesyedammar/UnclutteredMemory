"""P3 server tests: real HTTP over the real Store/Gate.

Every test spins a ThreadingHTTPServer on an ephemeral port and talks
to it with urllib (stdlib only, like the server). Judges are offline
stubs; the 429 test uses a judge that raises RateLimited, proving the
admit path quarantines through HTTP with no fallback model.
"""
import json
import logging
import threading
import urllib.request
import urllib.error

import pytest

from uncluttered_memory.gate import GateVote, JudgeClient, RuleJudge
from uncluttered_memory.jev_client import RateLimited
from uncluttered_memory.server import MemoryApp, RateLimiter, serve
from uncluttered_memory.store import Store

STORE_TEXT = "standup 9am daily"
QUAR_TEXT = "The weather was nice yesterday in some vague way"
DROP_TEXT = "ok"


class _HaltedJudge(JudgeClient):
    def vote(self, text, neighbors, facts):
        raise RateLimited("Jev free window rate-limited (HTTP 429)")


def _client(base):
    def post(path, payload):
        raw = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(base + path, data=raw,
                                     headers={"Content-Type":
                                              "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def get(path):
        try:
            with urllib.request.urlopen(base + path) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))
    return post, get


@pytest.fixture()
def live_server():
    store = Store(":memory:")
    httpd = serve("127.0.0.1", 0, store, RuleJudge())
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % port, store
    httpd.shutdown()
    thread.join(timeout=5)


def test_admit_recall_inject_status_roundtrip(live_server):
    base, _store = live_server
    post, get = _client(base)
    status, body = post("/admit", {"user": "alice", "text": STORE_TEXT,
                                   "source": "chat"})
    assert status == 200, body
    assert body["action"] == "STORE"
    assert isinstance(body["fact_id"], int)
    status, body = post("/recall", {"user": "alice",
                                    "query": "standup daily"})
    assert status == 200, body
    assert STORE_TEXT in body["texts"], body
    assert STORE_TEXT in body["packed"]
    status, body = post("/inject", {"user": "alice",
                                    "query": "standup daily"})
    assert status == 200, body
    assert STORE_TEXT in body["context"], body
    status, body = get("/status?user=alice")
    assert status == 200, body
    assert body["live"] == 1
    assert body["error_count"] == 0


def test_per_user_scoping_on_every_call(live_server):
    base, store = live_server
    post, get = _client(base)
    status, _ = post("/admit", {"user": "alice", "text": STORE_TEXT,
                                "source": "chat"})
    assert status == 200
    status, body = post("/recall", {"user": "bob",
                                    "query": "standup daily"})
    assert status == 200
    assert body["texts"] == [], body
    status, body = get("/status?user=bob")
    assert status == 200
    assert body["live"] == 0
    assert store.live("bob") == []
    for op_call in (lambda: post("/admit", {"text": STORE_TEXT}),
                    lambda: post("/recall", {"query": "x"}),
                    lambda: post("/inject", {"query": "x"}),
                    lambda: post("/status", {}),
                    lambda: get("/status")):
        status, body = op_call()
        assert status == 400, (op_call, body)
        assert "user" in body["error"]


def test_gate_quarantine_is_200_not_degrade(live_server):
    base, store = live_server
    post, _get = _client(base)
    status, body = post("/admit", {"user": "alice", "text": QUAR_TEXT,
                                   "source": "chat"})
    assert status == 200, body
    assert body["action"] == "QUARANTINE"
    assert body["quarantined"] is True
    assert "degraded" not in body
    assert isinstance(body["qid"], int)
    assert len(store.quarantined("alice")) == 1


def test_drop_text_reports_drop(live_server):
    base, store = live_server
    post, _get = _client(base)
    status, body = post("/admit", {"user": "alice", "text": DROP_TEXT,
                                   "source": "chat"})
    assert status == 200, body
    assert body["action"] == "DROP"
    assert store.live("alice") == []


def test_rate_call_cap_trips_with_429_and_log(caplog):
    # The fixture server uses default budgets; a tight limiter at the
    # app layer proves the trip, the log line, and the no-write rule.
    tight = RateLimiter(calls_per_min=2, chars_per_min=10 ** 9)
    store = Store(":memory:")
    app = MemoryApp(store, RuleJudge(), limiter=tight)
    assert app.handle("status", {"user": "u"})[0] == 200
    assert app.handle("status", {"user": "u"})[0] == 200
    with caplog.at_level(logging.ERROR,
                         logger="uncluttered_memory.server"):
        status, body = app.handle("status", {"user": "u"})
    assert status == 429
    assert body["rate_limited"] is True
    assert body["quarantined"] is False
    assert "retry_after_secs" in body
    assert any("RateBudgetExceeded" in r.message
               for r in caplog.records), \
        "refusal must emit one structured log line"
    # Refused calls store and quarantine nothing.
    status, _ = app.handle("admit", {"user": "u", "text": STORE_TEXT,
                                      "source": "chat"})
    assert status == 429
    assert store.live("u") == []
    assert store.quarantined("u") == []


def test_rate_cap_trips_over_http():
    store = Store(":memory:")
    tight = RateLimiter(calls_per_min=2, chars_per_min=10 ** 9)
    httpd = serve("127.0.0.1", 0, store, RuleJudge(), limiter=tight)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        post, _get = _client("http://127.0.0.1:%d" % port)
        assert post("/status", {"user": "u"})[0] == 200
        assert post("/status", {"user": "u"})[0] == 200
        status, body = post("/admit", {"user": "u", "text": STORE_TEXT,
                                       "source": "chat"})
        assert status == 429, body
        assert body["rate_limited"] is True
        # The refused admit stored and quarantined nothing.
        assert store.live("u") == []
        assert store.quarantined("u") == []
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def test_char_budget_trips():
    tight = RateLimiter(calls_per_min=10 ** 9, chars_per_min=10)
    app = MemoryApp(Store(":memory:"), RuleJudge(), limiter=tight)
    status, body = app.handle("admit", {"user": "u", "text": STORE_TEXT,
                                        "source": "chat"}, raw_chars=999)
    assert status == 429, body
    assert body["rate_limited"] is True


def test_kill_switch_env_refuses_every_endpoint(live_server, monkeypatch):
    base, store = live_server
    post, get = _client(base)
    status, _ = post("/admit", {"user": "alice", "text": STORE_TEXT,
                                "source": "chat"})
    assert status == 200  # alive before the switch
    monkeypatch.setenv("UNCLUTTER_KILL_SWITCH", "1")
    try:
        for op_call in (lambda: post("/admit", {"user": "alice",
                                                "text": STORE_TEXT}),
                        lambda: post("/recall", {"user": "alice",
                                                 "query": "standup"}),
                        lambda: post("/inject", {"user": "alice",
                                                 "query": "standup"}),
                        lambda: post("/status", {"user": "alice"}),
                        lambda: get("/status?user=alice")):
            status, body = op_call()
            assert status == 503, (op_call, body)
            assert "kill switch" in body["error"]
        # The killed admit stored nothing new.
        assert len(store.live("alice")) == 1
    finally:
        monkeypatch.delenv("UNCLUTTER_KILL_SWITCH", raising=False)


def test_kill_switch_file_refuses(tmp_path):
    kill = tmp_path / "KILL"
    kill.write_text("halt\n", encoding="utf-8")
    app = MemoryApp(Store(":memory:"), RuleJudge(), kill_file=str(kill))
    for op in ("admit", "recall", "inject", "status", "review"):
        payload = {"user": "u", "text": "x", "query": "x"}
        status, body = app.handle(op, payload)
        assert status == 503, (op, body)
        assert "kill switch" in body["error"]
        assert str(kill) in body["error"]


def test_429_degrade_quarantines_through_http():
    store = Store(":memory:")
    httpd = serve("127.0.0.1", 0, store, _HaltedJudge())
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        post, _get = _client("http://127.0.0.1:%d" % port)
        status, body = post("/admit", {"user": "alice",
                                       "text": STORE_TEXT, "source": "chat"})
        assert status == 429, body
        assert body["action"] == "QUARANTINE"
        assert body["quarantined"] is True
        assert body["degraded"] is True
        assert isinstance(body["qid"], int)
        rows = store.quarantined("alice")
        assert len(rows) == 1
        assert rows[0][1] == STORE_TEXT
        # A judge halt is not a coding bug: error_count stays zero.
        assert store.error_count == 0
        # Nothing leaked across users.
        assert store.quarantined("bob") == []
        assert store.live("alice") == []
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def test_unknown_path_and_bad_json(live_server):
    base, _store = live_server
    post, _get = _client(base)
    req = urllib.request.Request(base + "/nope", data=b"{}",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req)
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404
    bad = urllib.request.Request(base + "/admit", data=b"{not json",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(bad)
        assert False, "expected 400"
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_fake_judge_low_conf_quarantines_over_http():
    class _LowConf(JudgeClient):
        def vote(self, text, neighbors, facts):
            return GateVote(0.9, 5, 0.0, conf=0.1)

    store = Store(":memory:")
    app = MemoryApp(store, _LowConf())
    status, body = app.handle("admit", {"user": "u", "text": "x",
                                        "source": "s"})
    assert status == 200, body
    assert body["action"] == "QUARANTINE"
    assert "degraded" not in body
