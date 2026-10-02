"""SQLite store: provenance on every row, tombstones not rewrites."""
from __future__ import annotations

import sqlite3
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  source TEXT NOT NULL,
  created REAL NOT NULL,
  tombstoned_by INTEGER,
  UNIQUE(text)
);
"""


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def put(self, text: str, source: str) -> int:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO facts(text, source, created) VALUES(?,?,?)",
            (text, source, time.time()),
        )
        self.db.commit()
        row = self.db.execute("SELECT id FROM facts WHERE text=?", (text,)).fetchone()
        return row[0]

    def supersede(self, old_id: int, new_text: str, source: str) -> int:
        new_id = self.put(new_text, source)
        self.db.execute("UPDATE facts SET tombstoned_by=? WHERE id=?", (new_id, old_id))
        self.db.commit()
        return new_id

    def live(self) -> list:
        return self.db.execute(
            "SELECT id, text, source FROM facts WHERE tombstoned_by IS NULL"
        ).fetchall()
