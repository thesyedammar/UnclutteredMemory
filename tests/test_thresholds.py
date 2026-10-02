"""Thresholds live in one module; every decision cutoff is a parameter.

The round-2 finding was Gate.decide hardcoding `stop >= 0.58` next to a
durable_min parameter. These tests pin the parametrization of every
cutoff, the defaults living in thresholds.py, and the reason strings
echoing the effective value.
"""
import inspect
from pathlib import Path

from uncluttered_memory import thresholds as th
from uncluttered_memory.gate import FakeJudge, Gate, GateVote
from uncluttered_memory.recall import Recall

SRC = Path(__file__).resolve().parents[1] / "src" / "uncluttered_memory"


def test_thresholds_module_owns_the_defaults():
    assert th.MIN_CONF == 0.6
    assert th.PLAY_DROP == 0.7
    assert th.SENSITIVE_DROP == 0.7
    assert th.STOP_BLOCK == 0.58
    assert th.DURABLE_MIN == 0.58
    assert th.IMPORTANCE_MIN == 3
    assert th.RECALL_GATE == 0.58
    assert th.RECALL_BAND == 0.45
    assert th.RECALL_CAP == 8


def test_no_decision_cutoff_hardcoded_in_logic_modules():
    gate_src = (SRC / "gate.py").read_text(encoding="utf-8")
    recall_src = (SRC / "recall.py").read_text(encoding="utf-8")
    # the exact literal the round-2 finding called out, plus the band
    assert "0.58" not in gate_src
    assert "0.58" not in recall_src and "0.45" not in recall_src
    assert "0.58" in (SRC / "thresholds.py").read_text(encoding="utf-8")


def test_gate_decide_every_cutoff_is_a_parameter_defaulting_to_thresholds():
    sig = inspect.signature(Gate.decide)
    for name, val in (("importance_min", th.IMPORTANCE_MIN),
                      ("durable_min", th.DURABLE_MIN),
                      ("stop_block", th.STOP_BLOCK),
                      ("min_conf", th.MIN_CONF),
                      ("play_drop", th.PLAY_DROP),
                      ("sensitive_drop", th.SENSITIVE_DROP)):
        assert sig.parameters[name].default == val, name


def test_every_gate_cutoff_can_be_overridden():
    store_vote = Gate(FakeJudge({"x": GateVote(0.9, 5, 0.0)}))
    assert store_vote.decide("x").action == "STORE"
    assert store_vote.decide("x", durable_min=0.95).action == "DROP"
    assert store_vote.decide("x", importance_min=6).action == "DROP"

    stop = Gate(FakeJudge({"x": GateVote(0.9, 5, 0.6)}))
    assert stop.decide("x").action == "QUARANTINE"
    assert stop.decide("x", stop_block=0.7).action == "STORE"

    play = Gate(FakeJudge({"x": GateVote(0.9, 5, 0.0, play=0.8)}))
    assert play.decide("x").action == "DROP"
    assert play.decide("x", play_drop=0.9).action == "STORE"

    sens = Gate(FakeJudge({"x": GateVote(0.9, 5, 0.0, sensitive=0.8)}))
    assert sens.decide("x").action == "DROP"
    assert sens.decide("x", sensitive_drop=0.9).action == "STORE"

    conf = Gate(FakeJudge({"x": GateVote(0.9, 5, 0.0, conf=0.5)}))
    assert conf.decide("x").action == "QUARANTINE"
    assert conf.decide("x", min_conf=0.4).action == "STORE"


def test_reasons_echo_the_effective_threshold():
    g = Gate(FakeJudge({"x": GateVote(0.9, 5, 0.95)}))
    assert g.decide("x").reasons == ["stop>=0.58"]
    assert g.decide("x", stop_block=0.9).reasons == ["stop>=0.9"]
    p = Gate(FakeJudge({"x": GateVote(0.9, 5, 0.0, play=0.9)}))
    assert p.decide("x").reasons == ["play>0.7"]
    s = Gate(FakeJudge({"x": GateVote(0.9, 5, 0.0, sensitive=0.9)}))
    assert s.decide("x").reasons == ["sensitive>0.7"]


def test_recall_select_every_cutoff_is_a_parameter():
    sig = inspect.signature(Recall.select)
    assert sig.parameters["gate"].default == th.RECALL_GATE
    assert sig.parameters["band"].default == th.RECALL_BAND
    assert sig.parameters["cap"].default == th.RECALL_CAP
    r = Recall()
    scored = [("a", 0.5), ("b", 0.4)]
    assert r.select(scored) == []  # default gate cuts both
    assert r.select(scored, gate=0.3) == ["a", "b"]  # band floor 0.275
    assert r.select(scored, gate=0.3, band=0.1) == ["a"]  # floor 0.45
    many = [(str(i), 0.9) for i in range(12)]
    assert len(r.select(many, cap=3)) == 3
    assert len(r.select(many)) == th.RECALL_CAP


def test_char_budget_proxy_is_documented_and_pinned():
    """Chars-proxy boundary: budgets are char counts, packed whole-card.

    thresholds.py documents why chars stand in for tokens (the 4x
    rule), where the proxy mis-splits, and why packing cuts on
    whole-card boundaries. This test pins the documented behavior:
    the budget constants, the char (not token) accounting, and the
    whole-card cut in both packers.
    """
    assert th.INJECT_BUDGET_CHARS == 4000
    assert th.RECALL_PACK_BUDGET_CHARS == 4000
    doc = (SRC / "thresholds.py").read_text(encoding="utf-8")
    assert "4 chars" in doc or "4-char" in doc or "4x" in doc
    assert "whole-card" in doc
    assert "proxy" in doc
    from uncluttered_memory.inject import Injector
    small = "x" * 2500
    packed = Injector().pack([(small, 1.0), (small, 0.9)])
    assert packed == small  # second whole card would exceed 4000 chars
    packed_r = Recall().pack([small, small])
    assert packed_r == small
    exact = "y" * (th.INJECT_BUDGET_CHARS - 1)
    assert Injector().pack([(exact, 1.0)]) == exact
    assert Recall().pack([exact]) == exact
