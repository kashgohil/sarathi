"""SQLite-backed metadata store.

Holds:
  - docs           one row per ingested document (path, content hash, ingest time)
  - chunks         one row per chunk (links to LanceDB row by id)
  - transcripts    persisted live-session transcripts (subject to retention)
  - sessions       a session is a single listening window (start, end, title)

LanceDB owns the vector data; SQLite owns the relational metadata. We
keep the two in sync via the chunk `id` (string PK on both sides).

Retention: `transcripts` and `sessions` older than `retention_days` are
deleted by `vacuum_old`; doc rows persist (they are reusable indexed
content, not ephemeral conversation data).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id              TEXT PRIMARY KEY,            -- stable id (sha1 of source path)
    source          TEXT NOT NULL,
    title           TEXT,
    content_hash    TEXT NOT NULL,
    page_count      INTEGER,
    lang_primary    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chunks (
    id              TEXT PRIMARY KEY,            -- "<doc_id>:<chunk_idx>"
    doc_id          TEXT NOT NULL,
    chunk_idx       INTEGER NOT NULL,
    page            INTEGER,
    lang            TEXT,
    token_count     INTEGER,
    text            TEXT NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES docs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    title           TEXT,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at        TEXT
);

CREATE TABLE IF NOT EXISTS transcripts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    speaker_id      TEXT,
    lang            TEXT,
    start_s         REAL,
    end_s           REAL,
    text            TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_transcripts_session ON transcripts(session_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_created ON transcripts(created_at);
"""


@dataclass
class DocRow:
    id: str
    source: str
    title: str | None
    content_hash: str
    page_count: int | None
    lang_primary: str | None


def doc_id_for(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @contextmanager
    def tx(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def upsert_doc(
        self,
        *,
        source: str,
        title: str | None,
        content_hash: str,
        page_count: int | None,
        lang_primary: str | None,
    ) -> str:
        did = doc_id_for(source)
        with self.tx() as c:
            c.execute(
                """
                INSERT INTO docs (id, source, title, content_hash, page_count, lang_primary)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    content_hash = excluded.content_hash,
                    page_count = excluded.page_count,
                    lang_primary = excluded.lang_primary,
                    updated_at = datetime('now')
                """,
                (did, source, title, content_hash, page_count, lang_primary),
            )
        return did

    def insert_chunks(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        with self.tx() as c:
            c.executemany(
                """
                INSERT OR REPLACE INTO chunks
                  (id, doc_id, chunk_idx, page, lang, token_count, text)
                VALUES (:id, :doc_id, :chunk_idx, :page, :lang, :token_count, :text)
                """,
                rows,
            )
        return len(rows)

    def start_session(self, session_id: str, title: str | None = None) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO sessions (id, title) VALUES (?, ?) "
                "ON CONFLICT(id) DO NOTHING",
                (session_id, title),
            )

    def end_session(self, session_id: str) -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE sessions SET ended_at = datetime('now') WHERE id = ?",
                (session_id,),
            )

    def append_transcript(
        self,
        *,
        session_id: str,
        text: str,
        lang: str | None,
        speaker_id: str | None,
        start_s: float | None,
        end_s: float | None,
    ) -> int:
        with self.tx() as c:
            cur = c.execute(
                """
                INSERT INTO transcripts (session_id, speaker_id, lang, start_s, end_s, text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, speaker_id, lang, start_s, end_s, text),
            )
            return int(cur.lastrowid)

    def vacuum_old(self, retention_days: int) -> int:
        """Delete transcripts (and sessions whose transcripts are all gone)
        older than `retention_days`. Doc rows are preserved.

        Returns the number of transcript rows deleted.
        """
        cutoff = (
            dt.datetime.utcnow() - dt.timedelta(days=retention_days)
        ).strftime("%Y-%m-%d %H:%M:%S")
        with self.tx() as c:
            cur = c.execute(
                "DELETE FROM transcripts WHERE created_at < ?",
                (cutoff,),
            )
            deleted = cur.rowcount
            c.execute(
                """
                DELETE FROM sessions
                 WHERE ended_at IS NOT NULL
                   AND ended_at < ?
                   AND id NOT IN (SELECT DISTINCT session_id FROM transcripts)
                """,
                (cutoff,),
            )
        return deleted

    def close(self) -> None:
        self._conn.close()
