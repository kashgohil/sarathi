from __future__ import annotations

import datetime as dt
from pathlib import Path

from sarathi.store.sqlite import Store, doc_id_for


def test_doc_id_stable():
    assert doc_id_for("/foo/bar.pdf") == doc_id_for("/foo/bar.pdf")
    assert doc_id_for("/a") != doc_id_for("/b")


def test_upsert_doc_and_chunks(tmp_path: Path):
    s = Store(tmp_path / "test.db")
    did = s.upsert_doc(
        source="/x/y.pdf",
        title="Y",
        content_hash="abc",
        page_count=3,
        lang_primary="gu",
    )
    n = s.insert_chunks(
        [
            {
                "id": f"{did}:0",
                "doc_id": did,
                "chunk_idx": 0,
                "page": 1,
                "lang": "gu",
                "token_count": 42,
                "text": "નમસ્તે",
            },
            {
                "id": f"{did}:1",
                "doc_id": did,
                "chunk_idx": 1,
                "page": 1,
                "lang": "gu",
                "token_count": 30,
                "text": "દુનિયા",
            },
        ]
    )
    assert n == 2

    # Re-upsert same id replaces (no duplicate insert error).
    n2 = s.insert_chunks(
        [
            {
                "id": f"{did}:0",
                "doc_id": did,
                "chunk_idx": 0,
                "page": 1,
                "lang": "gu",
                "token_count": 50,
                "text": "નમસ્તે v2",
            }
        ]
    )
    assert n2 == 1


def test_session_lifecycle(tmp_path: Path):
    s = Store(tmp_path / "test.db")
    s.start_session("sess1", title="Test call")
    s.append_transcript(
        session_id="sess1",
        text="hello",
        lang="en",
        speaker_id=None,
        start_s=0.0,
        end_s=1.0,
    )
    s.end_session("sess1")
    # Backdate the session to verify retention math.
    s._conn.execute(
        "UPDATE sessions SET ended_at = ? WHERE id = ?",
        ((dt.datetime.utcnow() - dt.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"), "sess1"),
    )
    s._conn.execute(
        "UPDATE transcripts SET created_at = ? WHERE session_id = ?",
        ((dt.datetime.utcnow() - dt.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"), "sess1"),
    )
    s._conn.commit()

    deleted = s.vacuum_old(retention_days=15)
    assert deleted == 1
