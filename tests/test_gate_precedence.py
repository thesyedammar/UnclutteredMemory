"""Gate.decide branch precedence: first match wins, and the order is policy.

The checks in Gate.decide run in a fixed order: confidence, play,
sensitive, stop, durable plus importance, else drop. The order is a
documented policy decision, not an accident: confidence fails closed
before any content branch is read, play disposes of high-precision
junk first, sensitive takes the one disposition that retains nothing,
stop is the strongest deny among the remaining branches, and the only
admitting branch (durable plus importance) runs last so every deny
gets the first chance. The rationale lives in gate.py's module
docstring and, with the numeric cutoffs, in thresholds.py.

These tests pin the exact action and the exact reason string for
multi-signal input: the headline conflicts (sensitive against a stop
just above the block cutoff, play against a high stop, sensitive plus
play at once, every branch firing at once), every pair of branches
firing together, the partial-store pairs, and the boundary
comparisons (strict above for play and sensitive, at-or-above for
stop, durable, and importance), so a reordering of the checks cannot
land silently.
"""
import pytest

from uncluttered_memory.gate import FakeJudge, Gate, GateVote


def _decide(text, vote):
    return Gate(FakeJudge({text: vote})).decide(text)


# Each row: label, vote, expected action, expected reason string.
# Defaults: PLAY_DROP and SENSITIVE_DROP are strict (fire above),
# STOP_BLOCK, DURABLE_MIN, and IMPORTANCE_MIN are inclusive (fire at
# or above). The expected reason strings are the ones
# tests/test_thresholds.py pins; here they double as the branch
# identity evidence for multi-signal input.
PAIR_CASES = [
    ("conf+play", GateVote(0.9, 5, 0.0, play=0.85, conf=0.5),
     "QUARANTINE", ["uncertain-low-conf"]),
    ("conf+sensitive", GateVote(0.9, 5, 0.0, sensitive=0.9, conf=0.5),
     "QUARANTINE", ["uncertain-low-conf"]),
    ("conf+stop", GateVote(0.9, 5, 0.9, conf=0.5),
     "QUARANTINE", ["uncertain-low-conf"]),
    ("conf+store", GateVote(0.9, 5, 0.0, conf=0.5),
     "QUARANTINE", ["uncertain-low-conf"]),
    ("play+sensitive", GateVote(0.9, 5, 0.0, play=0.85, sensitive=0.9),
     "DROP", ["play>0.7"]),
    ("play+stop", GateVote(0.9, 5, 0.9, play=0.85),
     "DROP", ["play>0.7"]),
    ("play+store", GateVote(0.9, 5, 0.0, play=0.85),
     "DROP", ["play>0.7"]),
    ("sensitive+stop", GateVote(0.9, 5, 0.9, sensitive=0.9),
     "DROP", ["sensitive>0.7"]),
    ("sensitive+store", GateVote(0.9, 5, 0.0, sensitive=0.9),
     "DROP", ["sensitive>0.7"]),
    ("stop+store", GateVote(0.9, 5, 0.9),
     "QUARANTINE", ["stop>=0.58"]),
    ("store-durable-without-importance", GateVote(0.9, 2, 0.0),
     "DROP", ["not-durable-or-trivial"]),
    ("store-importance-without-durable", GateVote(0.5, 5, 0.0),
     "DROP", ["not-durable-or-trivial"]),
]


@pytest.mark.parametrize("label,vote,action,reasons", PAIR_CASES,
                         ids=[row[0] for row in PAIR_CASES])
def test_every_pair_of_branches_first_match_wins(label, vote, action, reasons):
    d = _decide("case-" + label, vote)
    assert d.action == action, (label, d)
    assert d.reasons == reasons, (label, d)


def test_sensitive_with_stop_just_above_block_drops_as_sensitive():
    """stop=0.6 would quarantine alone; sensitive owns the outcome."""
    d = _decide("s", GateVote(0.9, 5, 0.6, sensitive=0.9))
    assert d.action == "DROP"
    assert d.reasons == ["sensitive>0.7"]


def test_play_with_high_stop_drops_as_play():
    """stop=0.9 would quarantine alone; play owns the outcome."""
    d = _decide("p", GateVote(0.9, 5, 0.9, play=0.85))
    assert d.action == "DROP"
    assert d.reasons == ["play>0.7"]


def test_sensitive_and_play_together_drop_as_play():
    """Play runs before sensitive; both fire, play's reason is recorded."""
    d = _decide("sp", GateVote(0.9, 5, 0.0, play=0.85, sensitive=0.9))
    assert d.action == "DROP"
    assert d.reasons == ["play>0.7"]


def test_all_branches_fire_play_owns_the_disposition():
    """play, sensitive, stop, and store fire at once; play is first."""
    d = _decide("all", GateVote(0.9, 5, 0.9, play=0.85, sensitive=0.9))
    assert d.action == "DROP"
    assert d.reasons == ["play>0.7"]


def test_all_branches_with_low_conf_quarantine_first():
    """Every branch fires and confidence is low: abstention wins first."""
    d = _decide("all-low", GateVote(0.9, 5, 0.9, play=0.85,
                                    sensitive=0.9, conf=0.5))
    assert d.action == "QUARANTINE"
    assert d.reasons == ["uncertain-low-conf"]


def test_boundary_comparisons_strict_above_at_or_above():
    """At the exact cutoff: play and sensitive stay silent, the rest fire."""
    at_play = _decide("bp", GateVote(0.9, 5, 0.0, play=0.7))
    assert at_play.action == "STORE"
    assert at_play.reasons == ["durable+important"]
    just_above_play = _decide("bpa", GateVote(0.9, 5, 0.0, play=0.71))
    assert just_above_play.action == "DROP"
    assert just_above_play.reasons == ["play>0.7"]
    at_sensitive = _decide("bs", GateVote(0.9, 5, 0.0, sensitive=0.7))
    assert at_sensitive.action == "STORE"
    assert at_sensitive.reasons == ["durable+important"]
    at_stop = _decide("bst", GateVote(0.9, 5, 0.58))
    assert at_stop.action == "QUARANTINE"
    assert at_stop.reasons == ["stop>=0.58"]
    below_stop = _decide("bstb", GateVote(0.9, 5, 0.57))
    assert below_stop.action == "STORE"
    assert below_stop.reasons == ["durable+important"]
    at_store = _decide("bdu", GateVote(0.58, 3, 0.0))
    assert at_store.action == "STORE"
    assert at_store.reasons == ["durable+important"]


def test_precedence_holds_when_cutoffs_are_overridden():
    """The branch order is structural; overrides move the bars only."""
    vote = GateVote(0.9, 5, 0.9, sensitive=0.9)
    d = _decide("ov1", vote)
    assert d.action == "DROP"
    assert d.reasons == ["sensitive>0.7"]
    d2 = Gate(FakeJudge({"ov2": vote})).decide("ov2", sensitive_drop=0.95)
    assert d2.action == "QUARANTINE"
    assert d2.reasons == ["stop>=0.58"]
    d3 = Gate(FakeJudge({"ov3": vote})).decide(
        "ov3", sensitive_drop=0.95, stop_block=0.95)
    assert d3.action == "STORE"
    assert d3.reasons == ["durable+important"]
