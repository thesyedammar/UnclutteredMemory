"""Live independence: destructive acts need two differently worded live
Jev questions plus offline heterogeneous confirmation. No network."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

from uncluttered_memory import supersede as supmod
from uncluttered_memory.jev_client import (
    JevRelationJudge,
    live_confirmed_decide,
    live_relation_pair,
    offline_relation_pair,
)

ROOT = Path(__file__).resolve().parents[1]


class _Replay:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stub_live(choices_by_qid, captured=None):
    """Stub transport: answer per live question id from the request body."""

    def fake_urlopen(req, timeout=None):
        payload = json.loads(req.data.decode())
        questions = payload.get("questions", {})
        assert len(questions) == 1
        qid = next(iter(questions))
        if captured is not None:
            captured.append(payload)
        choice = choices_by_qid[qid]
        body = json.dumps({"answers": {qid: {"choice": choice}}}).encode()
        return _Replay(body)

    return mock.patch("urllib.request.urlopen", fake_urlopen)


def _live_pair():
    return live_relation_pair(api_key="k")


def test_live_pair_questions_differ_by_construction():
    direct, slot = _live_pair()
    assert direct.variant == "direct"
    assert slot.variant == "slot"
    qid_a, body_a = direct._question_id_and_body()
    qid_b, body_b = slot._question_id_and_body()
    assert qid_a != qid_b
    assert (body_a["instructions"] != body_b["instructions"])
    assert body_a["criteria"] != body_b["criteria"]
    # keys stay pinned so the two answers are comparable
    assert set(body_a["criteria"]) == set(body_b["criteria"])
    assert set(body_a["criteria"]) == {
        "supersede", "coexist", "conflict_unresolved"}


def test_identical_live_question_twice_is_rejected():
    a = JevRelationJudge(api_key="k", variant="direct")
    b = JevRelationJudge(api_key="k", variant="direct")
    off_a, off_b = offline_relation_pair()
    with pytest.raises(ValueError):
        live_confirmed_decide("old", "new", a, b, off_a, off_b)


def test_non_live_judges_are_rejected():
    off_a, off_b = offline_relation_pair()
    with pytest.raises(ValueError):
        live_confirmed_decide("old", "new", off_a, off_b, off_a, off_b)


def test_same_answer_different_question_agreement_proceeds():
    old = "the office is at 1 Main St"
    new = "the office moved to 2 Main St"
    live_a, live_b = _live_pair()
    off_a, off_b = offline_relation_pair()
    captured = []
    choices = {"rel": "supersede", "rel_confirm": "supersede"}
    with _stub_live(choices, captured):
        dec = live_confirmed_decide(old, new, live_a, live_b, off_a, off_b)
    assert dec.agreed and dec.action == "TOMBSTONE"
    assert dec.relation == "supersede"
    assert "live-plus-offline-agreed" in dec.reasons
    # the two live calls really asked different questions
    assert len(captured) == 2
    q0 = next(iter(captured[0]["questions"].values()))
    q1 = next(iter(captured[1]["questions"].values()))
    assert q0["instructions"] != q1["instructions"]
    assert q0["criteria"] != q1["criteria"]


def test_live_pair_disagreement_vetoes():
    old = "the office is at 1 Main St"
    new = "the office moved to 2 Main St"
    live_a, live_b = _live_pair()
    off_a, off_b = offline_relation_pair()
    choices = {"rel": "supersede", "rel_confirm": "coexist"}
    with _stub_live(choices):
        dec = live_confirmed_decide(old, new, live_a, live_b, off_a, off_b)
    assert dec.action == "KEEP" and not dec.agreed
    assert "live-pair-disagree" in dec.reasons
    s_store = __import__("uncluttered_memory.store",
                         fromlist=["Store"]).Store(auto_spot=False)
    old_id = s_store.put(old, "t")
    new_id = s_store.put(new, "t")
    assert supmod.apply(s_store, old_id, new_id, dec) is False
    assert s_store.tombstoned() == []


def test_offline_pair_disagreement_vetoes_despite_live_agreement():
    # crafted near-miss: Strict says unrelated, Lenient says supersede
    old, new = "the kettle is blue", "everything moved to the annex"
    live_a, live_b = _live_pair()
    off_a, off_b = offline_relation_pair()
    choices = {"rel": "supersede", "rel_confirm": "supersede"}
    with _stub_live(choices):
        dec = live_confirmed_decide(old, new, live_a, live_b, off_a, off_b)
    assert dec.action == "KEEP" and not dec.agreed
    assert "offline-pair-disagree" in dec.reasons


def test_live_offline_mismatch_vetoes():
    # offline pair agrees unrelated, live pair agrees supersede
    old, new = "the kettle is blue", "the toaster is silver"
    live_a, live_b = _live_pair()
    off_a, off_b = offline_relation_pair()
    choices = {"rel": "supersede", "rel_confirm": "supersede"}
    with _stub_live(choices):
        dec = live_confirmed_decide(old, new, live_a, live_b, off_a, off_b)
    assert dec.action == "KEEP" and not dec.agreed
    assert "live-offline-disagree" in dec.reasons


def _load_spotcheck():
    spec = importlib.util.spec_from_file_location(
        "live_spotcheck", ROOT / "scripts" / "live_spotcheck.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_spotcheck_live_verdict_confirms_with_offline_pair():
    mod = _load_spotcheck()
    from uncluttered_memory.gate import RuleJudge
    gate = RuleJudge()
    live_a, live_b = _live_pair()
    case = {"suite": "supersede", "old": "the office is at 1 Main St",
            "new": "the office moved to 2 Main St"}
    choices = {"rel": "supersede", "rel_confirm": "supersede"}
    with _stub_live(choices):
        assert mod.live_verdict(case, gate, live_a, live_b) == "TOMBSTONE"


def test_spotcheck_live_verdict_vetoes_without_offline_agreement():
    mod = _load_spotcheck()
    from uncluttered_memory.gate import RuleJudge
    gate = RuleJudge()
    live_a, live_b = _live_pair()
    case = {"suite": "supersede", "old": "the kettle is blue",
            "new": "everything moved to the annex"}
    choices = {"rel": "supersede", "rel_confirm": "supersede"}
    with _stub_live(choices):
        assert mod.live_verdict(case, gate, live_a, live_b) == "KEEP"


def test_spotcheck_live_verdict_rejects_identical_live_questions():
    mod = _load_spotcheck()
    from uncluttered_memory.gate import RuleJudge
    gate = RuleJudge()
    a = JevRelationJudge(api_key="k", variant="direct")
    b = JevRelationJudge(api_key="k", variant="direct")
    case = {"suite": "supersede", "old": "the office is at 1 Main St",
            "new": "the office moved to 2 Main St"}
    with pytest.raises(ValueError):
        mod.live_verdict(case, gate, a, b)
