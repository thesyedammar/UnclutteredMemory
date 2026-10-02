"""Human override and restore: override-then-read-back, restore of a
tombstone, and the put() dedupe contract now that the dead exact-text
fallback was removed from Store.put."""
import pytest

from uncluttered_memory import supersede as supmod
from uncluttered_memory.store import Store, content_hash


def test_human_override_restore_read_back():
    s = Store()
    old = s.put("meeting is at 3pm", "user")
    victim = s.put("meeting is at 4pm", "user")
    s.tombstone(old, victim, "supersede-agreed", "code")
    assert s.get(old)[4] == victim
    supmod.human_override(s, old, "restore", actor="human",
                          reason="wrong call")
    row = s.get(old)
    assert row[4] is None and row[5] is None and row[6] is None
    assert {t for _, t, _ in s.live()} == {"meeting is at 3pm",
                                           "meeting is at 4pm"}
    assert s.tombstoned() == []


def test_human_override_retire_read_back():
    s = Store()
    old = s.put("gate key is brass", "user")
    victim = s.put("gate key is steel", "user")
    supmod.human_override(s, old, "retire", actor="human",
                          target_id=victim, reason="user said so")
    row = s.get(old)
    assert row[4] == victim and row[5] == "user said so" and row[6] == "human"
    assert [t for _, t, _ in s.live()] == ["gate key is steel"]
    assert s.tombstoned() == [(old, "gate key is brass", "user", victim)]


def test_restore_of_tombstone_is_read_back_live():
    s = Store()
    old = s.put("trip on monday", "user")
    new = s.put("trip on tuesday", "user")
    s.tombstone(old, new, "supersede", "code")
    assert [fid for fid, _, _, _ in s.tombstoned()] == [old]
    s.restore(old)
    row = s.get(old)
    assert row[4] is None and row[5] is None and row[6] is None
    assert s.tombstoned() == []
    assert {t for _, t, _ in s.live()} == {"trip on monday",
                                           "trip on tuesday"}
    # the counterpart fact is untouched, and repeat restores are safe
    assert s.get(new)[4] is None
    s.restore(old)
    s.restore(new)
    assert {t for _, t, _ in s.live()} == {"trip on monday",
                                           "trip on tuesday"}


def test_override_then_put_read_back_same_row():
    """After an override the fact is still the same dedupe target."""
    s = Store()
    other = s.put("unrelated row", "user")
    fid = s.put("same fact", "email")
    s.tombstone(fid, other, "manual", "code")
    supmod.human_override(s, fid, "restore", actor="human")
    assert s.put("  same  fact ", "chat") == fid
    assert s.get(fid)[2] == "chat"
    assert s.get(fid)[4] is None


def test_human_override_rejects_bad_actions():
    s = Store()
    fid = s.put("x", "user")
    with pytest.raises(ValueError):
        supmod.human_override(s, fid, "delete")
    with pytest.raises(ValueError):
        supmod.human_override(s, fid, "retire")  # target_id required


def test_put_dedupes_by_normalized_content_hash_only():
    """The removed exact-text fallback is gone: dedupe is the hash."""
    s = Store()
    a = s.put("ship the build", "email")
    assert s.put("ship  the\tbuild", "chat") == a
    assert len(s.live()) == 1
    assert s.get(a)[2] == "chat"
    # case and punctuation are content, so those are distinct rows
    b = s.put("Ship the build", "chat")
    c = s.put("ship the build.", "chat")
    assert len({a, b, c}) == 3
    assert len(s.live()) == 3


def test_put_same_text_single_row_and_hash_stable():
    s = Store()
    ids = {s.put("repeat me", "a") for _ in range(5)}
    assert len(ids) == 1 and len(s.live()) == 1
    assert content_hash("repeat me") == content_hash("  repeat   me ")
