"""LanceDB-backed chunk store.

Schema for the `chunks` table:
  - id          str   (primary key, "{doc_id}:{chunk_idx}")
  - doc_id      str
  - source      str   (absolute path)
  - page        int
  - lang        str
  - text        str
  - sparse      str   (JSON-encoded {token_id: weight}; LanceDB has no native
                       sparse type, so we serialize. Sparse retrieval is
                       computed in-process — see hybrid.py.)
  - vector      vector(1024)  (BGE-M3 dense)
  - metadata    str   (JSON-encoded extras)

Why JSON for sparse: BGE-M3 sparse is small (typically <100 non-zero
weights per chunk) and we score it in Python anyway via dot product
over query/doc weights. Storing as JSON keeps the schema simple and
the per-query overhead negligible at our corpus scale (<100k chunks).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StoredChunk:
    id: str
    doc_id: str
    source: str
    page: int
    lang: str | None
    text: str
    vector: list[float] = field(default_factory=list)
    sparse: dict[int, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def _connect(db_path: Path):
    try:
        import lancedb
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "lancedb is required for retrieval. Install with: uv sync --extra ml"
        ) from e
    db_path.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(db_path))


def _schema(dim: int):
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("doc_id", pa.string()),
            pa.field("source", pa.string()),
            pa.field("page", pa.int32()),
            pa.field("lang", pa.string()),
            pa.field("text", pa.string()),
            pa.field("sparse", pa.string()),
            pa.field("metadata", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
        ]
    )


class LanceStore:
    """Open or create a LanceDB at `db_path` with a `chunks` table."""

    def __init__(self, db_path: Path, dim: int = 1024):
        self.db_path = Path(db_path)
        self.dim = dim
        self._db = _connect(self.db_path)
        if "chunks" in self._db.table_names():
            self._tbl = self._db.open_table("chunks")
        else:
            self._tbl = self._db.create_table("chunks", schema=_schema(dim))

    def upsert(self, chunks: list[StoredChunk]) -> int:
        if not chunks:
            return 0
        rows = [
            {
                "id": c.id,
                "doc_id": c.doc_id,
                "source": c.source,
                "page": int(c.page),
                "lang": c.lang or "",
                "text": c.text,
                "sparse": json.dumps(c.sparse),
                "metadata": json.dumps(c.metadata),
                "vector": c.vector,
            }
            for c in chunks
        ]
        # LanceDB merge_insert keys on `id`.
        self._tbl.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(
            rows
        )
        return len(rows)

    def delete_doc(self, doc_id: str) -> None:
        self._tbl.delete(f"doc_id = '{doc_id}'")

    def all_sparse(self) -> list[tuple[str, dict[int, float]]]:
        """Yield (id, sparse) pairs for in-process BM25-style scoring.

        Cheap at <100k chunks; revisit if corpus grows past that.
        """
        df = self._tbl.to_pandas()
        return [(row["id"], json.loads(row["sparse"]) or {}) for _, row in df.iterrows()]

    def search_dense(self, query_vec: list[float], k: int) -> list[dict]:
        result = self._tbl.search(query_vec).limit(k).to_list()
        # LanceDB returns _distance (lower is better for L2; for cosine the
        # smaller the better too with the default metric). Convert to
        # similarity score for downstream RRF (RRF only needs rank, but
        # we surface a score for inspection).
        for r in result:
            d = r.get("_distance", 0.0)
            r["score"] = 1.0 / (1.0 + d)
        return result

    def get_by_ids(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        clause = "id IN (" + ",".join(f"'{i}'" for i in ids) + ")"
        return self._tbl.search().where(clause).limit(len(ids)).to_list()

    def count(self) -> int:
        return self._tbl.count_rows()
