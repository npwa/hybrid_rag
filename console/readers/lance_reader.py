"""Read-only view of the LanceDB vector table (requirement C2).

LanceDB has no read-only open mode, so this wrapper exposes only counting and schema
inspection; it has no add/delete/index methods (tested in tests/test_readonly.py)."""
from __future__ import annotations

from pathlib import Path


class LanceReadOnly:
    def __init__(self, directory: Path, table: str):
        import lancedb
        self._table = lancedb.connect(str(directory)).open_table(table)

    def count_rows(self) -> int:
        return int(self._table.count_rows())

    def vector_dim(self) -> int | None:
        field = self._table.schema.field("vector")
        return getattr(field.type, "list_size", None)

    def has_ann_index(self) -> bool:
        try:
            return len(self._table.list_indices()) > 0
        except Exception:
            return False
