"""SQLite store: content-hash dedupe, provenance per row, soft tombstones."""
from __future__ import annotations

import hashlib
import sqlite3
import time

from .gate import Gate  # noqa: F401  (used in the admit() annotation)


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
"""

_MIGRATE_COLS = ("text_hash", "user", "tombstone_reason", "tombstone_actor")


def normalize(text: str) -> str:
    return " ".join(text.split())


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode()).hexdigest()


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(facts)")}
        for col in _MIGRATE_COLS:
            if col not in have:
                try:
                    self.db.execute("ALTER TABLE facts ADD COLUMN %s TEXT" % col)
                except sqlite3.OperationalError:
                    pass
        for fid, text in self.db.execute(
                "SELECT id, text FROM facts WHERE text_hash IS NULL").fetchall():
            self.db.execute("UPDATE facts SET text_hash=? WHERE id=?",
                            (content_hash(text), fid))
        self.db.execute("UPDATE facts SET user='local' WHERE user IS NULL")
        self.db.commit()

    def put(self, text: str, source: str, user: str = "local") -> int:
        h = content_hash(text)
        row = self.db.execute(
            "SELECT id, source FROM facts WHERE user=? AND text_hash=?",
            (user, h)).fetchone()
        if row is None:
            row = self.db.execute(
                "SELECT id, source FROM facts WHERE user=? AND text=?",
                (user, text)).fetchone()
        if row is not None:
            fid, old_source = row
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
            " tombstone_reason, tombstone_actor"
            " FROM facts WHERE id=?", (fact_id,)).fetchone()

    def supersede(self, old_id: int, new_text: str, source: str,
                  reason: str = "supersede", actor: str = "code") -> int:
        old = self.db.execute("SELECT text, user FROM facts WHERE id=?",
                              (old_id,)).fetchone()
        if old is None:
            return self.put(new_text, source)
        old_text, user = old
        if normalize(new_text) == normalize(old_text):
            return old_id
        new_id = self.put(new_text, source, user)
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
        self.db.execute(
            "UPDATE facts SET tombstoned_by=NULL, tombstone_reason=NULL,"
            " tombstone_actor=NULL WHERE id=?", (fact_id,))
        self.db.commit()

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

        A rate-limited judge never votes: the item lands in the quarantine
        table and the action says so. Store and gate stay decoupled.
        """
        try:
            d = gate.decide(text, [], [])
        except Exception:
            self.quarantine(text, "judge-halted", source, user)
            return "QUARANTINE"
        if d.action == "STORE":
            self.put(text, source, user)
        elif d.action == "QUARANTINE":
            self.quarantine(text, ";".join(d.reasons), source, user)
        return d.action