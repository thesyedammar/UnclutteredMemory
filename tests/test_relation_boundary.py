"""Boundary tests for the strict offline relation judge (round-3
finding): one shared content token was enough to accept a marker as
being about the same slot, so near-homonyms and address/number
near-misses could tombstone.

The minimum is now two content tokens beyond stopwords and numbers
(digits and spelled-out numerals). Every pair below shares fewer than
two such tokens, so the strict judge reads it as unrelated, the
lenient judge reads the marker, and decide() vetoes: both facts stay
live, nothing is tombstoned, nothing is marked as a conflict.
"""
from uncluttered_memory import supersede as supmod
from uncluttered_memory import thresholds as th
from uncluttered_memory.jev_client import (LenientRelationJudge,
                                           StrictRelationJudge,
                                           _content_tokens,
                                           _shared_content,
                                           offline_relation_pair)
from uncluttered_memory.store import Store


def _assert_veto(old, new):
    """The full boundary contract for a one-token pair."""
    assert _shared_content(old, new) == 1, (old, new)
    assert StrictRelationJudge().relation(old, new) == "unrelated"
    assert LenientRelationJudge().relation(old, new) in (
        "supersede", "conflict_unresolved")
    s = Store()
    old_id = s.put(old, "user")
    new_id = s.put(new, "user")
    dec = supmod.decide(old, new, *offline_relation_pair())
    assert dec.action == "KEEP" and not dec.agreed, (old, new, dec.action)
    assert supmod.apply(s, old_id, new_id, dec) is False
    assert s.tombstoned() == [] and s.conflicts() == []
    assert {t for _, t, *_ in s.live()} == {old, new}


def _assert_agreed_tombstone(old, new, shared_expected):
    assert _shared_content(old, new) == shared_expected, (old, new)
    assert StrictRelationJudge().relation(old, new) == "supersede"
    assert LenientRelationJudge().relation(old, new) == "supersede"
    s = Store()
    old_id = s.put(old, "user")
    new_id = s.put(new, "user")
    dec = supmod.decide(old, new, *offline_relation_pair())
    assert dec.agreed and dec.action == "TOMBSTONE", (old, new, dec.action)
    assert supmod.apply(s, old_id, new_id, dec) is True
    assert s.get(old_id)[4] == new_id
    assert [t for _, t, *_ in s.live()] == [new]


def test_shared_token_minimum_raised_to_two():
    assert th.RELATION_SHARED_TOKENS_MIN >= 2
    # stopwords and numbers (digits, ordinals, spelled-out numerals)
    # are not content; "7am" is a slot label, not a count
    assert _content_tokens("the 12th street nine ten 7am") == {"street", "7am"}


def test_single_shared_content_token_vetoes():
    # the shared token is the subject, and it is still not a slot
    _assert_veto("the kettle is blue", "the kettle was moved")


def test_near_homonym_subject_prefix_vetoes():
    # "studio" prefixes "studio annex": a near-homonym of the entity,
    # not the same slot as the studio opening time
    _assert_veto("the studio opens at nine",
                 "the studio annex moved to the north lot")


def test_shared_digit_is_not_a_slot_vetoes():
    # the number near-miss 3 / 3:30 shares no slot evidence beyond
    # "meeting", so the move must veto
    _assert_veto("the meeting is at 3", "the meeting moved to 3:30")


def test_shared_number_word_is_not_a_slot_vetoes():
    _assert_veto("the standup runs at nine",
                 "the standup moved from nine to ten")


def test_address_number_near_miss_vetoes():
    # same street name, different number and address type: the office
    # moving to Oak Avenue must not tombstone a delivery fact
    _assert_veto("the office is at 12 Oak Street",
                 "the delivery changed to 14 Oak Avenue")


def test_address_near_miss_one_slot_token_vetoes():
    # the spare key and the key share exactly one content token; the
    # move to a different address is not enough to tombstone
    _assert_veto("the spare key is at 12 Oak Street",
                 "the key moved to 14 Elm Court")


def test_two_shared_content_tokens_accept_and_tombstone():
    # exactly at the raised minimum: two content tokens are a slot
    _assert_agreed_tombstone("the office key is brass",
                             "the office key changed to steel", 2)


def test_shared_address_slot_tokens_accept_and_tombstone():
    # an address update that shares the subject and the street: three
    # content tokens, a genuine same-slot move
    _assert_agreed_tombstone("the office is at 12 Oak Street",
                             "the office moved to 14 Oak Street", 3)
