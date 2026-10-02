import sys

sys.path.insert(0, "src")

from uncluttered_memory.gate import FakeJudge, Gate, GateVote
from uncluttered_memory.store import Store
from uncluttered_memory.recall import Recall


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


def test_tombstone_not_rewrite():
    s = Store()
    old = s.put("ship tuesday", "agent")
    s.supersede(old, "ship thursday", "agent")
    texts = [t for _, t, _ in s.live()]
    assert texts == ["ship thursday"]


def test_recall_gate_band_cap():
    r = Recall()
    scored = [("a", 0.90), ("b", 0.84), ("c", 0.71), ("d", 0.22), ("e", 0.15)]
    assert r.select(scored) == ["a", "b", "c"]
    assert r.select([("x", 0.3)]) == []
    many = [(str(i), 0.9) for i in range(20)]
    assert len(r.select(many)) == 8
