"""Thresholds live in one module; every decision cutoff is a parameter.

The round-2 finding was Gate.decide hardcoding `stop >= 0.58` next to a
durable_min parameter. These tests pin the parametrization of every
cutoff, the defaults living in thresholds.py, and the reason strings
echoing the effective value.
"""
import inspect
from pathlib import Path
from unittest import mock

import pytest

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
    assert th.DEDUP_JACCARD == 0.85


def test_thresholds_module_owns_the_judge_vote_levels():
    # Every numeric RuleJudge output lives in thresholds.py: the
    # vote-level block moved out of gate.py, which keeps aliases only.
    assert th.FILLER_LEVELS == (0.05, 1, 0.1)
    assert th.FILLER_CONF == 0.9
    assert th.PLAY_LEVELS == (0.3, 1, 0.2)
    assert th.PLAY_SIGNAL == 0.85
    assert th.PLAY_CONF == 0.8
    assert th.SENSITIVE_LEVELS == (0.6, 2, 0.1)
    assert th.SENSITIVE_SIGNAL == 0.9
    assert th.SENSITIVE_CONF == 0.8
    assert th.DURABLE_DURABLE == 0.9
    assert th.DURABLE_STOP == 0.05
    assert th.DURABLE_CONF == 0.8
    assert th.DURABLE_HARD_IMPORTANCE == 5
    assert th.DURABLE_SOFT_IMPORTANCE == 4
    assert th.UNCERTAIN_LEVELS == (0.5, 2, 0.4)
    assert th.UNCERTAIN_CONF == 0.2
    assert th.FAIL_CLOSED_LEVELS == (0.5, 2, 0.5)
    assert th.FAIL_CLOSED_CONF == 0.0


def test_gate_vote_level_names_alias_thresholds():
    import uncluttered_memory.gate as gate_mod
    for name in ("FILLER_LEVELS", "FILLER_CONF", "PLAY_LEVELS",
                 "PLAY_SIGNAL", "PLAY_CONF", "SENSITIVE_LEVELS",
                 "SENSITIVE_SIGNAL", "SENSITIVE_CONF", "DURABLE_DURABLE",
                 "DURABLE_STOP", "DURABLE_CONF", "DURABLE_HARD_IMPORTANCE",
                 "DURABLE_SOFT_IMPORTANCE", "UNCERTAIN_LEVELS",
                 "UNCERTAIN_CONF"):
        assert getattr(gate_mod, name) == getattr(th, name), name


def test_rule_judge_emits_thresholds_values():
    from uncluttered_memory.gate import RuleJudge
    j = RuleJudge()
    filler = j.vote("ok", [], [])
    assert (filler.durable, filler.importance, filler.stop) == tuple(
        th.FILLER_LEVELS)
    assert filler.conf == th.FILLER_CONF
    play = j.vote("lol that meeting", [], [])
    assert (play.durable, play.importance, play.stop) == tuple(
        th.PLAY_LEVELS)
    assert play.play == th.PLAY_SIGNAL and play.conf == th.PLAY_CONF
    sens = j.vote("call 5551234567 now", [], [])
    assert (sens.durable, sens.importance, sens.stop) == tuple(
        th.SENSITIVE_LEVELS)
    assert (sens.sensitive == th.SENSITIVE_SIGNAL
            and sens.conf == th.SENSITIVE_CONF)
    hard = j.vote("insulin dose at 8am or she faints", [], [])
    assert (hard.durable, hard.importance, hard.stop) == (
        th.DURABLE_DURABLE, th.DURABLE_HARD_IMPORTANCE, th.DURABLE_STOP)
    assert hard.conf == th.DURABLE_CONF
    soft = j.vote("i prefer morning standup", [], [])
    assert (soft.durable, soft.importance, soft.stop) == (
        th.DURABLE_DURABLE, th.DURABLE_SOFT_IMPORTANCE, th.DURABLE_STOP)
    unsure = j.vote("some ordinary tuesday note", [], [])
    assert (unsure.durable, unsure.importance, unsure.stop) == tuple(
        th.UNCERTAIN_LEVELS)
    assert unsure.conf == th.UNCERTAIN_CONF
    closed = FakeJudge({}).vote("anything", [], [])
    assert (closed.durable, closed.importance, closed.stop) == tuple(
        th.FAIL_CLOSED_LEVELS)
    assert closed.conf == th.FAIL_CLOSED_CONF


def test_no_numeric_vote_literal_in_gate_source():
    import re
    gate_src = (SRC / "gate.py").read_text(encoding="utf-8")
    code_lines = [ln for ln in gate_src.splitlines()
                  if not ln.lstrip().startswith("#")]
    code = "\n".join(code_lines)
    floats = set(re.findall(r"(?<![\w.])\d+\.\d+", code))
    # Only the neutral GateVote dataclass defaults may appear: zero
    # signals and full confidence are type plumbing, not tuned levels.
    assert floats == {"0.0", "1.0"}, floats


def test_put_threshold_is_a_parameter_defaulting_to_thresholds():
    from uncluttered_memory.store import Store
    sig = inspect.signature(Store.put)
    assert sig.parameters["dedup_jaccard"].default == th.DEDUP_JACCARD
    s = Store()
    a = s.put("pack the picnic hamper for sunday", "email")
    assert s.put("sunday hamper picnic the pack for", "chat") == a
    assert s.put("sunday hamper picnic the pack for", "chat",
                 dedup_jaccard=2.0) != a


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


def test_thresholds_module_owns_the_live_confidence_curve():
    # The conf formula used to live inline in jev_client._judge_vote
    # as 0.9 - abs(durable - 0.5) * 0.05. It now lives here.
    assert th.CONF_BASE == 0.9
    assert th.CONF_MIDPOINT == 0.5
    assert th.CONF_SLOPE == 0.05
    assert th.durable_confidence(0.5) == pytest.approx(0.9)
    assert th.durable_confidence(0.0) == pytest.approx(0.875)
    assert th.durable_confidence(1.0) == pytest.approx(0.875)
    assert th.durable_confidence(0.85) == pytest.approx(
        0.9 - abs(0.85 - 0.5) * 0.05)


def test_no_numeric_boundary_in_jev_client_source():
    # No numeric decision boundary may live outside thresholds.py:
    # jev_client must read every vote-level float from th.*. The only
    # float literals allowed inline are transport plumbing (the 429
    # cooldown, full/zero confidence defaults, missing-answer sentinels),
    # never tuned levels.
    import ast
    src = (SRC / "jev_client.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    floats = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            floats.add(node.value)
    assert floats <= {30.0, 0.0, 1.0, -1.0}, floats
    assert "th.durable_confidence" in src
    assert "th.STOP_BLOCK_CHOICE" in src
    assert "0.9 - abs" not in src


def test_stop_key_coupling_is_pinned_and_loud():
    # The stop choice pair is one coupled unit: the question criteria
    # and the agreement cap must read the same two keys. A rename of
    # either key changes the cap instead of silently keeping old wiring.
    import uncluttered_memory.jev_client as jmod
    assert th.STOP_ALLOW_CHOICE == "s1"
    assert th.STOP_BLOCK_CHOICE == "s0"
    assert th.STOP_BLOCK_CHOICE != th.STOP_ALLOW_CHOICE
    captured = {}
    j = jmod.JevJudgeClient(api_key="k")

    def fake_evaluate(state, questions):
        captured.update(questions)
        return {"dur": {"noul": 0.85},
                "imp": {"choice": "s3"},
                "sens": {"noul": 0.1},
                "stop": {"choice": "s1",
                         "probabilities": {"s1": 0.9, "s0": 0.05}}}

    j.evaluate = fake_evaluate
    j.vote("the plan is settled", [], [])
    assert set(captured["stop"]["criteria"]) == {
        th.STOP_BLOCK_CHOICE, th.STOP_ALLOW_CHOICE}
    cap = jmod.JevJudgeClient._stop_agreement_cap(
        {"probabilities": {"s1": 0.9, "s0": 0.05}})
    assert cap == pytest.approx(th.STOP_AGREE_CAP + abs(0.9 - 0.05))
    with mock.patch.object(th, "STOP_BLOCK_CHOICE", "s9"):
        renamed = jmod.JevJudgeClient._stop_agreement_cap(
            {"probabilities": {"s1": 0.9, "s0": 0.05}})
    assert renamed == pytest.approx(th.STOP_AGREE_CAP + 0.9)
    assert renamed != pytest.approx(cap)


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
