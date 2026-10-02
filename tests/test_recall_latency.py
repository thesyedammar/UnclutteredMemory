"""Recall latency smoke: 5000 live rows stay inside a stated budget.

The SQL filter in Store.live is indexed (facts_live_user scoped,
facts_live unscoped), so row selection is logarithmic; the linear part
is caller-side token scoring plus Recall.select. This test pins the
whole recall read (live plus score plus select plus pack) on 5000 rows
inside RECALL_LATENCY_BUDGET_S. Rows are seeded with direct SQL,
bypassing put's write-time near-duplicate scan on purpose: that scan
is a separate linear cost documented on Store.put, not the read path
pinned here.
"""
import time

from uncluttered_memory.recall import Recall
from uncluttered_memory.store import Store, content_hash, token_jaccard

N_ROWS = 5000
RECALL_LATENCY_BUDGET_S = 5.0


def _seed_5k(store: Store) -> None:
    import time as _time
    now = _time.time()
    store.db.executemany(
        "INSERT INTO facts(text, text_hash, source, user, created)"
        " VALUES(?,?,?,?,?)",
        [("fact %d about the winter supply roster and depot hours" % i,
          content_hash(
              "fact %d about the winter supply roster and depot hours" % i),
          "seed", "local", now)
         for i in range(N_ROWS)])
    store.db.commit()


def test_live_and_queue_indexes_exist(tmp_path):
    s = Store(str(tmp_path / "m.db"))
    names = {r[0] for r in s.db.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "facts_live_user" in names
    assert "facts_live" in names
    assert "quarantine_user" in names


def test_live_queries_use_the_index(tmp_path):
    s = Store(str(tmp_path / "m.db"))
    scoped = s.db.execute(
        "EXPLAIN QUERY PLAN SELECT id, text, source FROM facts"
        " WHERE tombstoned_by IS NULL AND user=?",
        ("local",)).fetchall()
    assert any("facts_live_user" in str(r) for r in scoped), scoped
    unscoped = s.db.execute(
        "EXPLAIN QUERY PLAN SELECT id, text, source FROM facts"
        " WHERE tombstoned_by IS NULL ORDER BY id").fetchall()
    assert any("facts_live" in str(r) for r in unscoped), unscoped


def test_recall_on_5k_rows_within_budget(tmp_path):
    s = Store(str(tmp_path / "m.db"))
    _seed_5k(s)
    assert len(s.live("local")) == N_ROWS
    start = time.perf_counter()
    rows = s.live("local")
    scored = [(t, token_jaccard("winter supply roster query", t))
              for _, t, _ in rows]
    texts = Recall().select(scored)
    Recall().pack(texts)
    dt = time.perf_counter() - start
    assert dt < RECALL_LATENCY_BUDGET_S, \
        "recall on %d rows took %.2fs, budget %.1fs" % (
            N_ROWS, dt, RECALL_LATENCY_BUDGET_S)
