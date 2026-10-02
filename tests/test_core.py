"""P0 core tests, kept on branch-keyed stubs. The eval and P1 tests use
feature-keyed RuleJudge: these remain only to lock signature behavior."""
from uncluttered_memory.gate import FakeJudge, Gate, GateVote
from uncluttered_memory.inject import Injector
from uncluttered_memory.recall import Recall
from uncluttered_memory.store import Store


VOTES = {
    "My stop-loss is 8%": GateVote(durable=0.93, importance=5, stop=0.05),
    "Buy the whole exchange lol": GateVote(durable=0.2, importance=1, stop=0.1, play=0.94),
    "ok": GateVote(durable=0.05, importance=1, stop=0.1),
    "I am Batman": GateVote(durable=0.3, importance=1, stop=0.2, play=0.85),
    "Rahul's number is 98xxx": GateVote(durable=0.6, importance=2, stop=0.1, sensitive=0.9),
}


def test_five_lines_one_stored():
    g = Gate(FakeJudge(VOTES))
    actions = {t: g.decide(t).action for t in VOTES}
    assert actions["My stop-loss is 8%"] == "STORE"
    assert all(v == "DROP" for k, v in actions.items() if k != "My stop-loss is 8%")


def test_quarantine_path():
    g = Gate(FakeJudge({"x": GateVote(durable=0.9, importance=5, stop=0.7)}))
    d = g.decide("x")
    assert d.action == "QUARANTINE" and d.reasons == ["stop>=0.58"]


def test_borderline_durable_drops():
    g = Gate(FakeJudge({"x": GateVote(durable=0.57, importance=5, stop=0.0)}))
    assert g.decide("x").action == "DROP"


def test_tombstone_not_rewrite():
    s = Store()
    old = s.put("ship tuesday", "agent")
    s.supersede(old, "ship thursday", "agent")
    texts = [t for _, t, _ in s.live()]
    assert texts == ["ship thursday"]


def test_put_idempotent():
    s = Store()
    assert s.put("same", "a") == s.put("same", "a")
    assert len(s.live()) == 1


def test_recall_gate_band_cap():
    r = Recall()
    scored = [("a", 0.90), ("b", 0.84), ("c", 0.71), ("d", 0.22), ("e", 0.15)]
    assert r.select(scored) == ["a", "b", "c"]
    assert r.select([("x", 0.3)]) == []
    assert r.select([]) == []
    many = [(str(i), 0.9) for i in range(20)]
    assert len(r.select(many)) == 8


def test_band_floor_cuts_laggards():
    r = Recall()
    # at default gate the gate dominates (band floor 0.55 < gate 0.58):
    assert r.select([("best", 1.0), ("lag", 0.58)]) == ["best", "lag"]
    # band cuts once calibration lowers the gate:
    out = r.select([("best", 1.0), ("lag", 0.5)], gate=0.3)
    assert out == ["best"]


def test_pack_budget_whole_cards():
    r = Recall()
    out = r.pack(["a" * 100, "b" * 100, "c" * 100], budget_chars=205)
    assert out == "a" * 100 + "\n" + "b" * 100


def test_injector_orders_and_caps():
    inj = Injector(budget_chars=10)
    assert inj.pack([("low", 0.6), ("high", 0.9)]) == "high\nlow"
    assert inj.pack([("toolongcard", 0.9)]) == ""