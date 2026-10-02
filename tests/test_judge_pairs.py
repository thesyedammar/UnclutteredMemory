"""Paired-judge honesty: two DISTINCT offline relation heuristics that
genuinely disagree on crafted cases, and a decide() that vetoes every
destructive act unless both agree.

The offline pair is heterogeneous by construction (strict vs lenient),
and the eval routes decide() through it, so agreement means two
independent readings agreed, never one heuristic copied twice.
"""
from uncluttered_memory import supersede as supmod
from uncluttered_memory.gate import Gate, RuleJudge
from uncluttered_memory.jev_client import (LenientRelationJudge,
                                           StrictRelationJudge,
                                           offline_relation_pair)
from uncluttered_memory.store import Store

from eval.run import evaluate_suite, relation_judge_pair

#: Crafted near-misses where the two heuristics genuinely disagree.
#: (old, new, strict label, lenient label)
DISAGREEMENTS = (
    # lenient reads the update marker as a supersede; strict refuses
    # because the two texts share no content token (different slot).
    ("the kettle is blue", "everything moved to the annex",
     "unrelated", "supersede"),
    # lenient reads the negation as a clash; strict refuses for the
    # same shared-slot reason.
    ("the studio opens at nine", "that plan is not happening anymore",
     "unrelated", "conflict_unresolved"),
    # both signals present: strict takes the explicit negation, lenient
    # takes the update wording. Different priorities, different labels.
    ("the studio opens at nine",
     "the studio no longer opens at nine, it opens at ten now",
     "conflict_unresolved", "supersede"),
)

#: Crafted cases where the two heuristics agree, so acts may proceed.
AGREEMENTS = (
    ("the office is at 1 Main St", "the office moved to 2 Main St",
     "supersede"),
    ("I love morning runs", "I do not love morning runs anymore",
     "conflict_unresolved"),
    ("the kettle is blue", "the toaster is silver", "unrelated"),
)


def test_offline_pair_is_two_distinct_heuristics():
    a, b = offline_relation_pair()
    assert type(a) is StrictRelationJudge
    assert type(b) is LenientRelationJudge
    assert type(a) is not type(b)
    # the eval's pair factory is the same heterogeneous pair
    a2, b2 = relation_judge_pair()
    assert type(a2) is not type(b2)


def test_heuristics_genuinely_disagree_on_crafted_cases():
    strict, lenient = StrictRelationJudge(), LenientRelationJudge()
    for old, new, strict_label, lenient_label in DISAGREEMENTS:
        assert strict.relation(old, new) == strict_label
        assert lenient.relation(old, new) == lenient_label
        assert strict_label != lenient_label


def test_heuristics_agree_on_unambiguous_cases():
    strict, lenient = StrictRelationJudge(), LenientRelationJudge()
    for old, new, label in AGREEMENTS:
        assert strict.relation(old, new) == label
        assert lenient.relation(old, new) == label


def test_supersede_vetoed_on_disagreement():
    """A destructive act must not proceed on a disagreement."""
    old, new = "the kettle is blue", "everything moved to the annex"
    s = Store()
    old_id = s.put(old, "user")
    new_id = s.put(new, "user")
    dec = supmod.decide(old, new, StrictRelationJudge(),
                        LenientRelationJudge())
    assert dec.action == "KEEP" and not dec.agreed
    assert "disagree-veto" in dec.reasons
    assert supmod.apply(s, old_id, new_id, dec) is False
    assert s.tombstoned() == []
    assert s.conflicts() == []
    assert {t for _, t, *_ in s.live()} == {old, new}


def test_conflict_marking_vetoed_on_disagreement():
    """The clash-vs-supersede disagreement also vetoes, nothing marked."""
    old = "the studio opens at nine"
    new = "the studio no longer opens at nine, it opens at ten now"
    s = Store()
    old_id = s.put(old, "user")
    new_id = s.put(new, "user")
    dec = supmod.decide(old, new, StrictRelationJudge(),
                        LenientRelationJudge())
    assert dec.action == "KEEP" and not dec.agreed
    assert supmod.apply(s, old_id, new_id, dec) is False
    assert s.get(old_id)[4] is None and s.get(new_id)[4] is None
    assert s.get(old_id)[7] is None and s.get(new_id)[7] is None
    assert s.tombstoned() == [] and s.conflicts() == []


def test_agreed_supersede_proceeds_only_on_genuine_agreement():
    old, new = "the office is at 1 Main St", "the office moved to 2 Main St"
    s = Store()
    old_id = s.put(old, "user")
    new_id = s.put(new, "user")
    dec = supmod.decide(old, new, *offline_relation_pair())
    assert dec.agreed and dec.action == "TOMBSTONE"
    assert supmod.apply(s, old_id, new_id, dec)
    assert s.get(old_id)[4] == new_id
    assert [t for _, t, *_ in s.live()] == [new]


def test_agreed_conflict_marks_both_never_tombstones():
    old, new = "I love morning runs", "I do not love morning runs anymore"
    s = Store()
    old_id = s.put(old, "user")
    new_id = s.put(new, "user")
    dec = supmod.decide(old, new, *offline_relation_pair())
    assert dec.agreed and dec.action == "CONFLICT"
    assert dec.relation == "conflict_unresolved"
    assert supmod.apply(s, old_id, new_id, dec)
    assert s.tombstoned() == []
    assert s.get(old_id)[4] is None and s.get(new_id)[4] is None
    assert len(s.conflicts()) == 1


def test_pair_vetoes_what_a_copied_stub_would_tombstone():
    """The old theater: two copies of one stub agreed by construction.

    A copied pair (the same FakeRelationJudge votes twice) tombstones
    by construction; the heterogeneous pair turns the same crafted
    case into a veto, so the eval can no longer pass a destructive act
    on tautological agreement.
    """
    old, new = "the kettle is blue", "everything moved to the annex"
    copied = supmod.decide(old, new,
                           supmod.FakeRelationJudge({(old, new): "supersede"}),
                           supmod.FakeRelationJudge({(old, new): "supersede"}))
    paired = supmod.decide(old, new, *offline_relation_pair())
    assert copied.action == "TOMBSTONE"  # copy pair agrees by construction
    assert copied.agreed
    assert paired.action == "KEEP" and not paired.agreed


def test_eval_routes_decide_through_the_mismatched_pair():
    """evaluate_suite must use the heterogeneous pair, not a copy pair."""
    crafted = [
        {"old": "the kettle is blue", "new": "everything moved to the annex",
         "expect": "KEEP"},
        {"old": "the office is at 1 Main St",
         "new": "the office moved to 2 Main St", "expect": "TOMBSTONE"},
    ]
    rows, _ = evaluate_suite("supersede", crafted, Gate(RuleJudge()))
    assert [r[3] for r in rows] == [True, True]


def test_eval_pair_rejects_the_tautological_case():
    """Under the eval's pair the copied-stub case is a veto, so a case
    expecting TOMBSTONE for it would fail: the theater is gone."""
    crafted = [
        {"old": "the kettle is blue", "new": "everything moved to the annex",
         "expect": "TOMBSTONE"},
    ]
    rows, _ = evaluate_suite("supersede", crafted, Gate(RuleJudge()))
    assert rows[0][1] == "KEEP" and rows[0][3] is False
