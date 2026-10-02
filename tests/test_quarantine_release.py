"""Quarantine release flow: review, approve, deny, all end to end.

Approve releases the row live, deny drops it; both require a human
reason logged with actor human in the reviews table. Unknown qids
are refused with nothing written.
"""
import pytest

from uncluttered_memory import cli as climod
from uncluttered_memory.store import Store


def _seeded_db(tmp_path):
    db = tmp_path / "memory.db"
    s = Store(str(db))
    s.quarantine("the visa interview is on monday", "stop>=0.58", "agent")
    s.quarantine("lol nice", "uncertain-low-conf", "agent")
    return db


def test_approve_releases_live_and_logs_reason(tmp_path):
    db = _seeded_db(tmp_path)
    s = Store(str(db))
    fid = s.approve_quarantine(1, "checked, real duty", actor="human")
    assert [t for _, t, _ in s.live()] == ["the visa interview is on monday"]
    assert [qid for qid, _, _ in s.quarantined()] == [2]
    reviews = s.reviews()
    assert len(reviews) == 1
    _, qid, decision, reason, actor = reviews[0]
    assert (qid, decision, reason, actor) == (
        1, "approve", "checked, real duty", "human")
    assert s.get(fid)[1] == "the visa interview is on monday"


def test_deny_drops_and_logs_reason(tmp_path):
    db = _seeded_db(tmp_path)
    s = Store(str(db))
    s.deny_quarantine(2, "play, nothing to keep", actor="human")
    assert s.live() == []
    assert [qid for qid, _, _ in s.quarantined()] == [1]
    reviews = s.reviews()
    assert len(reviews) == 1
    _, qid, decision, reason, actor = reviews[0]
    assert (qid, decision, reason, actor) == (
        2, "deny", "play, nothing to keep", "human")


def test_reason_required_and_unknown_qid_refused(tmp_path):
    db = _seeded_db(tmp_path)
    s = Store(str(db))
    with pytest.raises(ValueError):
        s.approve_quarantine(1, "   ")
    with pytest.raises(ValueError):
        s.deny_quarantine(1, "")
    with pytest.raises(KeyError):
        s.approve_quarantine(999, "looks fine")
    with pytest.raises(KeyError):
        s.deny_quarantine(999, "junk")
    assert len(s.quarantined()) == 2
    assert s.reviews() == []
    assert s.live() == []


def test_release_is_privileged_bypass_with_no_review_row(tmp_path):
    """Store.release moves the row live with no reason and no audit row.

    It is the privileged bypass for code and operator tooling (tests,
    migration, harness reseeding), never the human review flow.
    """
    db = _seeded_db(tmp_path)
    s = Store(str(db))
    fid = s.release(1)
    assert [t for _, t, _ in s.live()] == ["the visa interview is on monday"]
    assert [qid for qid, _, _ in s.quarantined()] == [2]
    assert s.reviews() == []
    assert s.get(fid)[1] == "the visa interview is on monday"


def test_release_vs_approve_contrast(tmp_path):
    """release needs no reason and logs nothing; approve needs a reason
    and logs it. Human quarantine decisions must use approve/deny."""
    import inspect
    assert "reason" not in inspect.signature(Store.release).parameters
    assert "reason" in inspect.signature(Store.approve_quarantine).parameters
    db = _seeded_db(tmp_path)
    s = Store(str(db))
    s.release(1)
    assert s.reviews() == []
    with pytest.raises(ValueError):
        s.approve_quarantine(2, "   ")
    assert s.reviews() == []
    fid = s.approve_quarantine(2, "checked, keep it", actor="human")
    assert s.get(fid)[1] == "lol nice"
    reviews = s.reviews()
    assert len(reviews) == 1
    _, qid, decision, reason, actor = reviews[0]
    assert (qid, decision, reason, actor) == (
        2, "approve", "checked, keep it", "human")


def test_release_unknown_qid_refused_with_nothing_written(tmp_path):
    db = _seeded_db(tmp_path)
    s = Store(str(db))
    with pytest.raises(KeyError):
        s.release(999)
    assert len(s.quarantined()) == 2
    assert s.reviews() == []
    assert s.live() == []


def test_cli_review_lists_the_queue(tmp_path, capsys):
    db = _seeded_db(tmp_path)
    rc = climod.main(["review", "--db", str(db)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "qid=1" in out and "qid=2" in out
    assert "awaiting human review" in out


def test_cli_review_empty_queue(tmp_path, capsys):
    db = tmp_path / "empty.db"
    Store(str(db))
    rc = climod.main(["review", "--db", str(db)])
    assert rc == 0
    assert "empty" in capsys.readouterr().out


def test_cli_approve_end_to_end(tmp_path, capsys):
    db = _seeded_db(tmp_path)
    rc = climod.main(["approve", "--db", str(db), "--qid", "1",
                      "--reason", "checked with the team"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "released as fact" in out
    assert "by human" in out
    s = Store(str(db))
    assert [t for _, t, _ in s.live()] == ["the visa interview is on monday"]
    assert s.reviews()[0][3] == "checked with the team"


def test_cli_deny_end_to_end(tmp_path, capsys):
    db = _seeded_db(tmp_path)
    rc = climod.main(["deny", "--db", str(db), "--qid", "2",
                      "--reason", "play, drop it"])
    assert rc == 0
    assert "dropped by human" in capsys.readouterr().out
    s = Store(str(db))
    assert s.live() == []
    assert [qid for qid, _, _ in s.quarantined()] == [1]
    assert s.reviews()[0][2] == "deny"


def test_cli_approve_unknown_qid_refused(tmp_path, capsys):
    db = _seeded_db(tmp_path)
    rc = climod.main(["approve", "--db", str(db), "--qid", "999",
                      "--reason", "looks fine"])
    assert rc == 2
    assert "no quarantined row" in capsys.readouterr().out
    assert Store(str(db)).reviews() == []


def test_cli_deny_unknown_qid_refused(tmp_path, capsys):
    db = _seeded_db(tmp_path)
    rc = climod.main(["deny", "--db", str(db), "--qid", "999",
                      "--reason", "junk"])
    assert rc == 2
    assert "no quarantined row" in capsys.readouterr().out
    assert Store(str(db)).reviews() == []
