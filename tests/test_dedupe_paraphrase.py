"""Paraphrase-aware dedupe: token-set Jaccard second stage in Store.put.

Stage one (exact normalized hash) is unchanged. These tests pin stage
two: genuine near-duplicates merge, near-miss distinct facts stay
separate, the threshold is a parameter defaulting to
thresholds.DEDUP_JACCARD, and boundary/user-scope/tombstone behavior
is exact.
"""
import inspect

from uncluttered_memory import thresholds as th
from uncluttered_memory.store import Store, token_jaccard


def test_reordered_words_merge():
    s = Store()
    a = s.put("pack the picnic hamper for sunday", "email")
    assert s.put("sunday hamper picnic the pack for", "chat") == a
    assert len(s.live()) == 1


def test_dropped_word_in_long_fact_merges():
    # 6 of 7 tokens shared: 6/7 = 0.857, above the 0.85 default.
    s = Store()
    a = s.put("please pack the picnic hamper for sunday", "email")
    assert s.put("pack the picnic hamper for sunday", "chat") == a
    assert len(s.live()) == 1


def test_duplicated_word_collapses_to_same_set():
    s = Store()
    a = s.put("pack the picnic hamper", "email")
    assert s.put("pack pack the picnic hamper", "chat") == a
    assert len(s.live()) == 1


def test_whitespace_plus_reorder_merges():
    s = Store()
    a = s.put("pack the picnic hamper", "email")
    assert s.put("  hamper\tpicnic  the pack ", "chat") == a
    assert len(s.live()) == 1


def test_near_dupe_hit_refreshes_source():
    s = Store()
    a = s.put("pack the picnic hamper for sunday", "email")
    assert s.put("sunday hamper picnic the pack for", "chat") == a
    assert s.get(a)[2] == "chat"


def test_single_word_swap_in_short_fact_stays_distinct():
    # 3/5 = 0.60: a changed content word is a different fact.
    s = Store()
    a = s.put("rinse the clay pots", "email")
    b = s.put("rinse the clay pans", "chat")
    assert a != b
    assert len(s.live()) == 2


def test_added_word_at_boundary_stays_distinct():
    # 4/5 = 0.80, just under the 0.85 default (mirrors g-dedupe-0013).
    assert token_jaccard("fold the winter coats today",
                         "fold the winter coats") == 4 / 5
    s = Store()
    a = s.put("fold the winter coats today", "email")
    b = s.put("fold the winter coats", "chat")
    assert a != b
    assert len(s.live()) == 2


def test_case_difference_stays_distinct():
    s = Store()
    a = s.put("Pack the picnic hamper", "email")
    b = s.put("pack the picnic hamper", "chat")
    assert a != b
    assert len(s.live()) == 2


def test_trailing_period_stays_distinct():
    s = Store()
    a = s.put("paint the garden shed.", "email")
    b = s.put("paint the garden shed", "chat")
    assert a != b
    assert len(s.live()) == 2


def test_plural_difference_stays_distinct():
    s = Store()
    a = s.put("trim the hedge lines", "email")
    b = s.put("trim the hedge line", "chat")
    assert a != b
    assert len(s.live()) == 2


def test_lowered_threshold_merges_near_miss():
    s = Store()
    a = s.put("rinse the clay pots", "email")
    assert s.put("rinse the clay pans", "chat", dedup_jaccard=0.5) == a
    assert len(s.live()) == 1


def test_disabled_threshold_keeps_reorder_distinct():
    # No Jaccard exceeds 1.0, so 2.0 turns the fuzzy stage off.
    s = Store()
    a = s.put("pack the picnic hamper for sunday", "email")
    b = s.put("sunday hamper picnic the pack for", "chat",
              dedup_jaccard=2.0)
    assert a != b
    assert len(s.live()) == 2


def test_threshold_default_is_thresholds_value():
    assert (inspect.signature(Store.put)
            .parameters["dedup_jaccard"].default) == th.DEDUP_JACCARD
    assert th.DEDUP_JACCARD == 0.85


def test_exact_threshold_value_merges():
    s = Store()
    a = s.put("fold the winter coats today", "email")
    assert s.put("fold the winter coats", "chat",
                 dedup_jaccard=4 / 5) == a
    assert len(s.live()) == 1


def test_just_above_threshold_splits():
    s = Store()
    a = s.put("fold the winter coats today", "email")
    b = s.put("fold the winter coats", "chat", dedup_jaccard=0.81)
    assert a != b
    assert len(s.live()) == 2


def test_near_dupe_never_crosses_user_scope():
    s = Store()
    a = s.put("pack the picnic hamper for sunday", "email",
              user="alice")
    b = s.put("sunday hamper picnic the pack for", "chat", user="bob")
    assert a != b
    assert [t for _, t, _ in s.live(user="alice")] == [
        "pack the picnic hamper for sunday"]
    assert [t for _, t, _ in s.live(user="bob")] == [
        "sunday hamper picnic the pack for"]


def test_tombstoned_near_dupe_inserts_fresh_row():
    # Resurrection stays exact-only: a fuzzy match against dead text
    # must not revive a possibly unrelated row.
    s = Store()
    fid = s.put("pack the picnic hamper for sunday", "email")
    other = s.put("unrelated fact row here", "email")
    s.tombstone(fid, other, "supersede-agreed", "code")
    fresh = s.put("sunday hamper picnic the pack for", "chat")
    assert fresh != fid
    assert s.get(fid)[4] == other
    assert fresh in [r[0] for r in s.live()]


def test_empty_and_single_token_texts_are_safe():
    s = Store()
    assert s.put("", "a") == s.put("   ", "b")
    a = s.put("hi", "a")
    b = s.put("hi there", "a")
    assert a != b
    assert token_jaccard("", "hi") == 0.0
    assert token_jaccard("", "") == 1.0
