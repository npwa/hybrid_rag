"""Dense leg: LanceDB search — step-5-requirements.md §2 step 1."""
from __future__ import annotations

import lancedb

from query.config import QueryConfig


def open_table(config: QueryConfig):
    db = lancedb.connect(str(config.lancedb_dir))
    return db.open_table(config.lancedb_table)


def dense_search(tbl, vector: list[float], limit: int) -> list[dict]:
    return tbl.search(vector).limit(limit).to_list()
