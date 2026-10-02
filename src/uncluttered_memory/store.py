"""SQLite store: content-hash dedupe, provenance per row, soft tombstones."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time

from .gate import Gate  # noqa: F401  (used in the admit() annotation)
from .jev_client import JevError

_LOG = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
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
CREATE TABLE IF NOT EXISTS quarantine (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  reason TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  user TEXT NOT NULL DEFAULT 'local',
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS conflicts (
  id INTEGER PRIMARY KEY,
  old_id INTEGER NOT NULL,
  new_id INTEGER NOT NULL,
  relation TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  actor TEXT NOT NULL DEFAULT 'code',
  created REAL NOT NULL
);
"""

_MIGRATE_COLS = {"text_hash": "TEXT", "user": "TEXT",
                 "tombstone_reason": "TEXT", "tombstone_actor": "TEXT",
                 "conflict_with": "INTEGER"}


def normalize(text: str) -> str:
    return " ".join(text.split())


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode()).hexdigest()


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        #: Explicit counter of unexpected exceptions raised inside
        #: admit(). Judge halts quarantine and do not count; coding
        #: bugs count here, are logged, and propagate.
        self.error_count = 0
        self.db.executescript(SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(facts)")}
        for col, typ in _MIGRATE_COLS.items():
            if col not in have:
                try:
                    self.db.execute(
                        "ALTER TABLE facts ADD COLUMN %s %s" % (col, typ))
                except sqlite3.OperationalError:
                    pass
        for fid, text in self.db.execute(
                "SELECT id, text FROM facts WHERE text_hash IS NULL").fetchall():
            self.db.execute("UPDATE facts SET text_hash=? WHERE id=?",
                            (content_hash(text), fid))
        self.db.execute("UPDATE facts SET user='local' WHERE user IS NULL")
        self.db.commit()

    def _clear_tombstone_and_conflict_marks(self, fact_id: int) -> None:
        """Shared clean path for restore() and put() resurrection.

        Clears the tombstone fields and the conflict marks on both
        sides (own conflict_with, the counterpart mark only where it
        still points back), plus any conflicts-table rows naming this
        fact. Callers commit. Both restore() and the put() resurrect
        branch call this helper so the two paths cannot drift.
        """
        row = self.db.execute(
            "SELECT conflict_with FROM facts WHERE id=?",
            (fact_id,)).fetchone()
        counterpart = row[0] if row is not None else None
        self.db.execute(
            "UPDATE facts SET tombstoned_by=NULL, tombstone_reason=NULL,"
            " tombstone_actor=NULL, conflict_with=NULL WHERE id=?",
            (fact_id,))
        if counterpart is not None:
            self.db.execute(
                "UPDATE facts SET conflict_with=NULL WHERE id=?"
                " AND conflict_with=?", (counterpart, fact_id))
        self.db.execute(
            "DELETE FROM conflicts WHERE old_id=? OR new_id=?",
            (fact_id, fact_id))

    def put(self, text: str, source: str, user: str = "local") -> int:
        """Insert or dedupe by normalized content hash.

        Dedupe key is (user, text_hash). A repeat put of live text
        returns the existing id (refreshing source when it changed).
        A repeat put of tombstoned text resurrects the row as live:
        text, source and created take the new put values (new put is
        new life), and the row is cleaned through the same shared
        path as restore() (tombstone fields plus conflict marks on
        both sides and conflicts-table rows), so a conflict-marked
        then tombstoned fact re-put live reads fully clean. The same
        id is returned, now visible in live(). No silent-swallow
        path: every put either returns a live id or inserts a new
        live row.
        """
        # Dedupe is by normalized content hash only. An exact-text
        # fallback used to sit here; it was dead (a row whose text
        # matches also carries the hash of that text, because every
        # write computes the hash and the migration backfills legacy
        # rows), so it was removed instead of kept as unreachable code.
        h = content_hash(text)
        row = self.db.execute(
            "SELECT id, source, tombstoned_by FROM facts"
            " WHERE user=? AND text_hash=?",
            (user, h)).fetchone()
        if row is not None:
            fid, old_source, tombstoned_by = row
            if tombstoned_by is not None:
                self.db.execute(
                    "UPDATE facts SET text=?, source=?, created=?"
                    " WHERE id=?",
                    (text, source, time.time(), fid))
                self._clear_tombstone_and_conflict_marks(fid)
                self.db.commit()
                return fid
            if old_source != source:
                self.db.execute("UPDATE facts SET source=? WHERE id=?",
                                (source, fid))
                self.db.commit()
            return fid
        cur = self.db.execute(
            "INSERT INTO facts(text, text_hash, source, user, created)"
            " VALUES(?,?,?,?,?)", (text, h, source, user, time.time()))
        self.db.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    def get(self, fact_id: int):
        return self.db.execute(
            "SELECT id, text, source, user, tombstoned_by,"
            " tombstone_reason, tombstone_actor, conflict_with"
            " FROM facts WHERE id=?", (fact_id,)).fetchone()

    def supersede(self, old_id: int, new_text: str, source: str,
                  user: "str | None" = None,
                  reason: str = "supersede", actor: str = "code") -> int:
        """Scope-explicit supersede: the caller user threads every path.

        The dedupe key is (user, text_hash) and live(user=...) pairs
        with it, so a supersede that silently falls back to the
        default user would land the row in a scope the caller never
        reads. There is no silent fallback here:

        - known id: the row owner scope applies; an explicit caller
          user that differs from the row owner raises ValueError
          (cross-user supersede is refused, nothing is written).
        - missing id with an explicit user: the new text is stored
          in that caller scope and the new id is returned.
        - missing id without a user: KeyError(old_id); no row is
          silently inserted into the default scope.
        """
        old = self.db.execute("SELECT text, user FROM facts WHERE id=?",
                              (old_id,)).fetchone()
        if old is None:
            if user is None:
                raise KeyError(old_id)
            return self.put(new_text, source, user)
        old_text, row_user = old
        if user is not None and user != row_user:
            raise ValueError(
                "supersede scope mismatch: fact %d belongs to user %r,"
                " caller asked as user %r" % (old_id, row_user, user))
        if normalize(new_text) == normalize(old_text):
            # Same content would otherwise return the id without
            # touching the row, which silently swallows a
            # put-after-tombstone. Route through put() so a
            # tombstoned row is resurrected as live.
            return self.put(new_text, source, row_user)
        new_id = self.put(new_text, source, row_user)
        if new_id == old_id:
            return old_id
        self.tombstone(old_id, new_id, reason, actor)
        return new_id

    def tombstone(self, old_id: int, new_id: int, reason: str = "",
                  actor: str = "code") -> None:
        self.db.execute(
            "UPDATE facts SET tombstoned_by=?, tombstone_reason=?,"
            " tombstone_actor=? WHERE id=?", (new_id, reason, actor, old_id))
        self.db.commit()

    def restore(self, fact_id: int) -> None:
        """Restore a fact to fully clean live state.

        Clears the tombstone fields and also clears conflict marks on
        both sides: the fact's own conflict_with, the counterpart
        fact's conflict_with (only where it still points back, so a
        newer clash on the counterpart is never clobbered), and any
        rows in the conflicts table naming this fact. A clash is a
        pair property, so leaving one side marked after a human
        restore would read as a dangling unresolved clash; the
        restored fact and its former counterpart both read clean.
        Repeat restores are safe no-ops. Shares
        _clear_tombstone_and_conflict_marks with put() resurrection.
        """
        self._clear_tombstone_and_conflict_marks(fact_id)
        self.db.commit()

    def mark_conflict(self, old_id: int, new_id: int,
                      reason: str = "conflict_unresolved",
                      actor: str = "code") -> None:
        """Mark an unresolved clash: both facts stay live and both rows
        carry the counterpart mark, plus a row in the conflicts table."""
        self.db.execute(
            "INSERT INTO conflicts(old_id, new_id, relation, reason, actor,"
            " created) VALUES(?,?,?,?,?,?)",
            (old_id, new_id, "conflict_unresolved", reason, actor, time.time()))
        self.db.execute("UPDATE facts SET conflict_with=? WHERE id=?",
                        (new_id, old_id))
        self.db.execute("UPDATE facts SET conflict_with=? WHERE id=?",
                        (old_id, new_id))
        self.db.commit()

    def conflicts(self, user=None) -> list:
        """Unresolved-clash pairs. Both member facts are still live.

        A clash is a pair property, so a user filter attributes by
        either side: rows where the old fact or the new fact belongs
        to the user. Filtering by the old side only would hide a
        clash from the new side owner, who is equally party to it.
        """
        if user is None:
            return self.db.execute(
                "SELECT old_id, new_id, relation, reason, actor"
                " FROM conflicts ORDER BY id").fetchall()
        return self.db.execute(
            "SELECT c.old_id, c.new_id, c.relation, c.reason, c.actor"
            " FROM conflicts c JOIN facts fo ON fo.id=c.old_id"
            " JOIN facts fn ON fn.id=c.new_id"
            " WHERE fo.user=? OR fn.user=? ORDER BY c.id", (user, user)).fetchall()

    def live(self, user=None) -> list:
        if user is None:
            return self.db.execute(
                "SELECT id, text, source FROM facts"
                " WHERE tombstoned_by IS NULL ORDER BY id").fetchall()
        return self.db.execute(
            "SELECT id, text, source FROM facts"
            " WHERE tombstoned_by IS NULL AND user=? ORDER BY id",
            (user,)).fetchall()

    def tombstoned(self, user=None) -> list:
        if user is None:
            return self.db.execute(
                "SELECT id, text, source, tombstoned_by FROM facts"
                " WHERE tombstoned_by IS NOT NULL ORDER BY id").fetchall()
        return self.db.execute(
            "SELECT id, text, source, tombstoned_by FROM facts"
            " WHERE tombstoned_by IS NOT NULL AND user=? ORDER BY id",
            (user,)).fetchall()

    def quarantine(self, text: str, reason: str, source: str = "",
                   user: str = "local") -> int:
        cur = self.db.execute(
            "INSERT INTO quarantine(text, reason, source, user, created)"
            " VALUES(?,?,?,?,?)", (text, reason, source, user, time.time()))
        self.db.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    def quarantined(self, user=None) -> list:
        if user is None:
            return self.db.execute(
                "SELECT id, text, reason FROM quarantine ORDER BY id").fetchall()
        return self.db.execute(
            "SELECT id, text, reason FROM quarantine WHERE user=? ORDER BY id",
            (user,)).fetchall()

    def release(self, qid: int, source: str = "") -> int:
        row = self.db.execute(
            "SELECT text, source, user FROM quarantine WHERE id=?",
            (qid,)).fetchone()
        if row is None:
            raise KeyError(qid)
        text, qsource, user = row
        fid = self.put(text, source or qsource, user)
        self.db.execute("DELETE FROM quarantine WHERE id=?", (qid,))
        self.db.commit()
        return fid

    def admit(self, text: str, source: str, gate: Gate,
              user: str = "local") -> str:
        """Write path: gate decides, or quarantine when the judge halts.

        Only judge-halt exceptions quarantine: the JevError family
        (rate limit, bad key, transport failure, malformed judge
        answer) means the judge could not vote, so the item lands in
        the quarantine table and nothing is stored, dropped, or
        invented. Any other exception is a coding bug in the write
        path: it increments the explicit error_count, emits one
        structured log line (time, op, input hash, error type), and
        propagates. It is never swallowed as a quarantine.

        The counted partition covers the whole write path, not just
        the vote: gate.decide failures log op "admit", while
        failures inside the follow-up self.put or self.quarantine
        (including the judge-halted quarantine write itself) log op
        "admit.put" or "admit.quarantine", then propagate. The op
        names which write step raised.
        """
        def _counted(op: str, fn):
            try:
                return fn()
            except Exception as e:
                self.error_count += 1
                _LOG.error(json.dumps({
                    "time": time.time(),
                    "op": op,
                    "input_hash": content_hash(text),
                    "error_type": type(e).__name__,
                }, sort_keys=True))
                raise

        try:
            d = gate.decide(text, [], [])
        except JevError:
            _counted("admit.quarantine", lambda: self.quarantine(
                text, "judge-halted", source, user))
            return "QUARANTINE"
        except Exception as e:
            self.error_count += 1
            _LOG.error(json.dumps({
                "time": time.time(),
                "op": "admit",
                "input_hash": content_hash(text),
                "error_type": type(e).__name__,
            }, sort_keys=True))
            raise
        if d.action == "STORE":
            _counted("admit.put", lambda: self.put(text, source, user))
        elif d.action == "QUARANTINE":
            _counted("admit.quarantine", lambda: self.quarantine(
                text, ";".join(d.reasons), source, user))
        return d.action