"""Per-user memory cap (master plan): parametrized, loud, scoped.

A fresh insert that would grow a user scope past its live-fact cap is
refused: put() raises MemoryCapExceeded (nothing stored live) and
admit() holds the item in quarantine with reason "per-user-memory-cap"
(never counted as a coding bug). Merges and exact-text hits add no row
and never trip the cap; each user scope counts separately; None means
unbounded.
"""
import inspect

import pytest

from uncluttered_memory import thresholds as th
from uncluttered_memory.gate import Gate, RuleJudge
from uncluttered_memory.store import MemoryCapExceeded, Store


def test_cap_is_a_threshold_and_a_constructor_parameter():
    assert th.PER_USER_MEMORY_CAP == 10000
    assert th.MEMORY_CAP_QUARANTINE_REASON == "per-user-memory-cap"
    sig = inspect.signature(Store.__init__)
    assert sig.parameters["per_user_memory_cap"].default == (
        th.PER_USER_MEMORY_CAP)
    assert Store()._per_user_memory_cap == th.PER_USER_MEMORY_CAP


def test_fresh_insert_at_cap_refused_loudly():
    s = Store(per_user_memory_cap=2)
    a = s.put("first standing fact", "email", user="u")
    b = s.put("second standing fact", "email", user="u")
    with pytest.raises(MemoryCapExceeded) as ei:
        s.put("third standing fact", "email", user="u")
    assert ei.value.user == "u" and ei.value.cap == 2 and ei.value.live == 2
    assert [r[0] for r in s.live(user="u")] == [a, b]
    assert s.error_count == 0


def test_merge_at_cap_still_merges_no_new_row():
    """A near-dupe of a stored fact merges at cap instead of refusing."""
    s = Store(per_user_memory_cap=1)
    a = s.put("pack the picnic hamper for sunday", "email", user="u")
    assert s.put("sunday hamper picnic the pack for", "chat",
                 user="u") == a
    assert len(s.live(user="u")) == 1


def test_exact_text_hit_at_cap_returns_existing_id():
    s = Store(per_user_memory_cap=1)
    a = s.put("the lease renews in march", "email", user="u")
    assert s.put("the lease renews in march", "chat", user="u") == a
    assert len(s.live(user="u")) == 1


def test_resurrection_at_cap_is_not_a_fresh_insert():
    """Put-after-tombstone keeps the row count: cap must not trip."""
    s = Store(per_user_memory_cap=2)
    a = s.put("trip on monday", "email", user="u")
    other = s.put("trip on tuesday", "email", user="u")
    s.tombstone(a, other, "manual", "code")
    assert len(s.live(user="u")) == 1
    back = s.put("trip  on monday", "chat", user="u")
    assert back == a
    assert len(s.live(user="u")) == 2


def test_cap_is_per_user_scope():
    s = Store(per_user_memory_cap=1)
    s.put("alice fact", "email", user="alice")
    with pytest.raises(MemoryCapExceeded):
        s.put("alice second", "email", user="alice")
    # bob's scope is untouched by alice's cap
    b = s.put("bob fact", "email", user="bob")
    assert [r[0] for r in s.live(user="bob")] == [b]


def test_none_cap_is_unbounded():
    s = Store(per_user_memory_cap=None)
    for i in range(50):
        s.put("fact number %d" % i, "email", user="u")
    assert len(s.live(user="u")) == 50


def test_admit_at_cap_quarantines_with_reason_not_a_bug():
    s = Store(per_user_memory_cap=1)
    g = Gate(RuleJudge())
    assert s.admit("prefer standup at 9am", "chat", g, user="u") == "STORE"
    action = s.admit("the report deadline is friday", "chat", g, user="u")
    assert action == "QUARANTINE"
    rows = s.quarantined(user="u")
    assert len(rows) == 1
    assert rows[0][1] == "the report deadline is friday"
    assert rows[0][2] == th.MEMORY_CAP_QUARANTINE_REASON
    assert len(s.live(user="u")) == 1
    # The cap hold is not a coding bug.
    assert s.error_count == 0


def test_admit_at_cap_merge_still_stores_no_quarantine():
    """A near-dupe admit at cap merges: no cap hold, nothing queued."""
    s = Store(per_user_memory_cap=1)
    g = Gate(RuleJudge())
    assert s.admit("prefer standup at 9am", "chat", g, user="u") == "STORE"
    # reordered wording: near-dupe of the stored fact, no new row
    action = s.admit("standup at 9am prefer", "chat", g, user="u")
    assert action == "STORE"
    assert s.quarantined(user="u") == []
    assert len(s.live(user="u")) == 1


def test_admit_at_cap_scoped_to_user():
    s = Store(per_user_memory_cap=1)
    g = Gate(RuleJudge())
    assert s.admit("prefer standup at 9am", "chat", g, user="alice") == "STORE"
    assert s.admit("the report deadline is friday", "chat", g,
                   user="alice") == "QUARANTINE"
    assert s.admit("prefer standup at 9am", "chat", g, user="bob") == "STORE"
    assert s.quarantined(user="bob") == []


def test_memory_app_admit_at_cap_answers_quarantine_not_429():
    """The server layer answers 200 QUARANTINE with the cap reason.

    A cap hold is a normal disposition, not a judge halt: the caller
    sees the item is held for review, with the machine-readable
    reason, and no error_count increment.
    """
    from uncluttered_memory.server import MemoryApp

    store = Store(":memory:", per_user_memory_cap=1)
    app = MemoryApp(store, RuleJudge())
    status, body = app.handle("admit", {"user": "u",
                                        "text": "prefer standup at 9am",
                                        "source": "chat"})
    assert status == 200 and body["action"] == "STORE"
    status, body = app.handle("admit", {"user": "u",
                                        "text": "the report deadline is friday",
                                        "source": "chat"})
    assert status == 200, body
    assert body["action"] == "QUARANTINE"
    assert body["quarantined"] is True
    assert body["reason"] == th.MEMORY_CAP_QUARANTINE_REASON
    assert "degraded" not in body
    assert store.error_count == 0
