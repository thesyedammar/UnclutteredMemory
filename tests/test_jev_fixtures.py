"""Fixture-driven tests for the native Jev response parser. No network.

Bodies under tests/fixtures are replayed through the real client code
(request build -> _post -> evaluate -> _judge_vote, and
JevRelationJudge.relation) with urllib.request.urlopen stubbed to serve
the recorded bytes. The recorded files are raw live response bodies;
the derived files are hand-built failure variants of the same shape.
"""
import json
from pathlib import Path
from unittest import mock

import pytest

from uncluttered_memory import supersede as supmod
from uncluttered_memory import thresholds as th
from uncluttered_memory.gate import Gate
from uncluttered_memory.jev_client import (ENDPOINT, JevError,
                                           JevJudgeClient,
                                           JevRelationJudge)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _Replay:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def replay(name, capture=None):
    body = (FIXTURES / name).read_bytes()

    def fake_urlopen(req, timeout=None):
        if capture is not None:
            capture["url"] = req.full_url
            capture["body"] = json.loads(req.data.decode())
            capture["headers"] = dict(req.headers)
        return _Replay(body)

    return mock.patch("urllib.request.urlopen", fake_urlopen)


def test_recorded_stop_loss_gate_vote_parses():
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_stop_loss_recorded.json"):
        v = j.vote("My stop-loss is 8%", [], [])
    assert v.durable == pytest.approx(0.69)
    assert v.importance == 5  # s4 critical constraint on the 1..5 scale
    assert v.sensitive == pytest.approx(0.22)
    assert v.stop == 0.0
    assert v.conf >= 0.6


def test_recorded_stop_loss_gate_decides_store():
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_stop_loss_recorded.json"):
        d = Gate(j).decide("My stop-loss is 8%")
    assert d.action == "STORE"


def test_recorded_play_gate_vote_parses_trivial_level():
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_play_recorded.json"):
        v = j.vote("Buy the whole exchange lol", [], [])
    assert v.durable == pytest.approx(0.2)
    assert v.importance == 1  # s0 trivial maps to 1, not out of range
    assert v.stop == 0.0
    assert v.sensitive == pytest.approx(0.02)


def test_recorded_play_gate_decides_drop():
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_play_recorded.json"):
        d = Gate(j).decide("Buy the whole exchange lol")
    assert d.action == "DROP"


def test_recorded_relation_response_parses():
    j = JevRelationJudge(api_key="k")
    with replay("jev_relation_recorded.json"):
        rel = j.relation("office is at 1 Main St", "office is at 2 Main St")
    assert rel == "supersede"


def test_recorded_relation_feeds_the_decision():
    j = JevRelationJudge(api_key="k")
    with replay("jev_relation_recorded.json"):
        dec = supmod.decide("office is at 1 Main St",
                            "office is at 2 Main St", j, j)
    assert dec.relation == "supersede" and dec.action == "TOMBSTONE"


def test_replayed_request_carries_pinned_model_and_session():
    capture = {}
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_stop_loss_recorded.json", capture):
        j.vote("My stop-loss is 8%", [], [])
    assert capture["url"] == ENDPOINT
    assert capture["body"]["model"] == "jev-1.13-free"
    headers = {k.lower(): v for k, v in capture["headers"].items()}
    assert headers["x-opencode-session"] == "hermes-go-static-7f3a9c2e"
    assert headers["authorization"] == "Bearer k"


def test_derived_out_of_range_noul_fails_closed():
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_out_of_range.json"):
        with pytest.raises(JevError):
            j.vote("anything", [], [])


def test_derived_missing_answers_fails_closed():
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_missing_answers.json"):
        with pytest.raises(JevError):
            j.vote("anything", [], [])


def test_derived_missing_importance_choice_fails_closed():
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_missing_choice.json"):
        with pytest.raises(JevError):
            j.vote("anything", [], [])


def test_derived_probability_alias_parses():
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_probability_alias.json"):
        v = j.vote("the plan is settled", [], [])
    assert v.durable == pytest.approx(0.75)
    assert v.importance == 3  # s2 useful
    assert v.stop == 0.0


def test_derived_score_level_answer_extracts():
    j = JevJudgeClient(api_key="k")
    with replay("jev_score_level.json"):
        answers = j.evaluate(
            {"memory": {"text": "the plan is settled"}},
            {"score_q": {"type": "score", "instructions": "score it"}})
    assert j._answer_value(answers["score_q"] or {}, "score") == 4


def test_stop_choice_mapping_is_bimodal_and_fail_closed():
    """Stop mapping pin: s1 -> 0.0, s0 -> 1.0, missing -> 1.0.

    A judge that fails to pick allow (block choice, absent answer,
    unreadable choice) reads as block, fail closed.
    """
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_stop_agreed.json"):
        v = j.vote("the plan is settled", [], [])
    assert v.stop == 0.0
    with replay("jev_gate_stop_block.json"):
        v = j.vote("the plan is settled", [], [])
    assert v.stop == 1.0
    with replay("jev_gate_stop_missing.json"):
        v = j.vote("the plan is settled", [], [])
    assert v.stop == 1.0


def test_stop_block_and_missing_quarantine_at_stop_cutoff():
    """s0 and unable-to-pick both land at QUARANTINE via the stop path."""
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_stop_block.json"):
        d = Gate(j).decide("the plan is settled")
    assert d.action == "QUARANTINE"
    assert d.reasons == ["stop>=%g" % th.STOP_BLOCK]
    with replay("jev_gate_stop_missing.json"):
        d = Gate(j).decide("the plan is settled")
    assert d.action == "QUARANTINE"
    assert d.reasons == ["stop>=%g" % th.STOP_BLOCK]


def test_stop_split_agreement_quarantines_on_confidence():
    """conf falls below MIN_CONF purely on stop-question disagreement.

    Same STORE-worthy values as the agreed fixture (durable 0.85, s3,
    allow choice); only the stop probabilities differ (near-tie), so
    the quarantine comes from judge agreement alone, not the values.
    """
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_stop_split.json"):
        v = j.vote("the plan is settled", [], [])
    assert v.stop == 0.0
    assert v.conf == pytest.approx(th.STOP_AGREE_CAP + abs(0.51 - 0.49))
    assert v.conf < th.MIN_CONF
    with replay("jev_gate_stop_split.json"):
        d = Gate(j).decide("the plan is settled")
    assert d.action == "QUARANTINE"
    assert d.reasons == ["uncertain-low-conf"]


def test_stop_agreed_margin_keeps_durable_confidence_and_stores():
    """Comfortable stop margin leaves conf at the durable-derived value."""
    j = JevJudgeClient(api_key="k")
    with replay("jev_gate_stop_agreed.json"):
        v = j.vote("the plan is settled", [], [])
    assert v.conf == pytest.approx(th.durable_confidence(0.85))
    assert v.conf >= th.MIN_CONF
    with replay("jev_gate_stop_agreed.json"):
        d = Gate(j).decide("the plan is settled")
    assert d.action == "STORE"
