"""Judge provenance on facts rows: stored on every judged write path.

Every facts row carries four provenance columns (gate_action,
importance, judge, decided_at). admit(STORE) fills them from the
gate decision; put() and supersede() accept them as keywords and
write them on inserts, resurrections, and merges. A ghostwriter
direct SQL insert leaves them NULL, so a judged row is
distinguishable from an unjudged row at read time through both
get() and live(). Old databases without the columns migrate
cleanly on open.
"""
import sqlite3
import time
from types import SimpleNamespace

from uncluttered_memory.gate import (FakeJudge, Gate, GateVote, RuleJudge,
                                     judge_name)
from uncluttered_memory.store import Store, content_hash

STORE_VOTE = GateVote(durable=0.9, importance=5, stop=0.0)

LEGACY_SCHEMA = """
CREATE TABLE facts (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  text_hash TEXT NOT NULL,
  source TEXT NOT NULL,
  user TEXT NOT NULL DEFAULT 'local',
  created REAL NOT NULL,
  tombstoned_by INTEGER,
  tombstone_reason TEXT,
  tombstone_actor TEXT,
  conflict_with INTEGER,
  UNIQUE(user, text_hash)
);
"""


def test_gate_decision_carries_importance_and_judge():
    d = Gate(FakeJudge({"t": STORE_VOTE})).decide("t")
    assert d.action == "STORE"
    assert d.importance == 5
    assert d.judge == "stub:FakeJudge"


def test_judge_name_stub_vs_live_model():
    assert judge_name(RuleJudge()) == "stub:RuleJudge"
    assert judge_name(FakeJudge({})) == "stub:FakeJudge"
    live = SimpleNamespace(model="jev-1.13-free")
    assert judge_name(live) == "jev-1.13-free"


def test_admit_store_row_carries_judge_provenance():
    s = Store()
    before = time.time()
    action = s.admit("my stop-loss is 8%", "email",
                     Gate(FakeJudge({"my stop-loss is 8%": STORE_VOTE})))
    assert action == "STORE"
    rows = s.live()
    assert len(rows) == 1
    fid, text, source, gate_action, importance, judge, decided_at = rows[0]
    assert (fid, text, source) == (1, "my stop-loss is 8%", "email")
    assert gate_action == "STORE"
    assert importance == 5
    assert judge == "stub:FakeJudge"
    assert decided_at is not None and decided_at >= before
    row = s.get(fid)
    assert len(row) == 12
    assert row[8:] == ("STORE", 5, "stub:FakeJudge", decided_at)


def test_ghostwriter_direct_insert_reads_null_provenance():
    s = Store()
    ghost_text = "ghost row with no gate vote"
    s.db.execute(
        "INSERT INTO facts(text, text_hash, source, user, created)"
        " VALUES(?,?,?,?,?)",
        (ghost_text, content_hash(ghost_text), "ghost", "local",
         time.time()))
    s.db.commit()
    judged = s.admit("my stop-loss is 8%", "email",
                      Gate(FakeJudge({"my stop-loss is 8%": STORE_VOTE})))
    assert judged == "STORE"
    ghost = s.get(1)
    assert ghost[8:] == (None, None, None, None)
    live = {r[0]: r for r in s.live()}
    assert live[1][3:] == (None, None, None, None)
    assert live[2][3:] == ("STORE", 5, "stub:FakeJudge", live[2][6])
    assert live[2][6] is not None
    # judged and ghostwriter rows are distinguishable at read time
    assert live[1][3:] != live[2][3:]
    assert s.get(1)[8:] != s.get(2)[8:]


def test_put_writes_provenance_on_insert_and_resurrection():
    s = Store()
    fid = s.put("standing tuesday review", "email",
                gate_action="STORE", importance=4,
                judge="stub:FakeJudge", decided_at=123.0)
    assert s.get(fid)[8:] == ("STORE", 4, "stub:FakeJudge", 123.0)
    other = s.put("unrelated filler row", "email")
    s.tombstone(fid, other, "supersede-agreed", "code")
    back = s.put("standing tuesday review", "chat",
                 gate_action="STORE", importance=5,
                 judge="stub:RuleJudge", decided_at=456.0)
    assert back == fid
    assert s.get(fid)[8:] == ("STORE", 5, "stub:RuleJudge", 456.0)


def test_plain_reput_never_clobbers_judged_provenance():
    s = Store()
    fid = s.admit("my stop-loss is 8%", "email",
                  Gate(FakeJudge({"my stop-loss is 8%": STORE_VOTE})))
    assert fid == "STORE"
    row_id = s.live()[0][0]
    before = s.get(row_id)[8:]
    assert before[0] == "STORE"
    assert s.put("my stop-loss is 8%", "chat") == row_id
    assert s.get(row_id)[8:] == before


def test_supersede_forwards_provenance_to_new_row():
    s = Store()
    old = s.put("ship tuesday", "agent")
    new = s.supersede(old, "ship thursday", "agent",
                      gate_action="STORE", importance=4,
                      judge="stub:FakeJudge", decided_at=789.0)
    assert new != old
    assert s.get(new)[8:] == ("STORE", 4, "stub:FakeJudge", 789.0)


def test_old_db_without_provenance_columns_migrates_cleanly(tmp_path):
    path = str(tmp_path / "legacy.db")
    db = sqlite3.connect(path)
    db.executescript(LEGACY_SCHEMA)
    legacy_text = "legacy row from before provenance"
    db.execute(
        "INSERT INTO facts(text, text_hash, source, user, created)"
        " VALUES(?,?,?,?,?)",
        (legacy_text, content_hash(legacy_text), "old", "local",
         time.time()))
    db.commit()
    db.close()
    s = Store(path)
    have = {r[1] for r in s.db.execute("PRAGMA table_info(facts)")}
    assert {"gate_action", "importance", "judge",
            "decided_at"} <= have
    row = s.get(1)
    assert row[1] == legacy_text
    assert row[8:] == (None, None, None, None)
    assert [r[0] for r in s.live()] == [1]
    assert s.live()[0][3:] == (None, None, None, None)
    # the migrated db takes judged writes like a fresh one
    action = s.admit("my stop-loss is 8%", "email",
                     Gate(FakeJudge({"my stop-loss is 8%": STORE_VOTE})))
    assert action == "STORE"
    assert s.get(2)[8] == "STORE"
