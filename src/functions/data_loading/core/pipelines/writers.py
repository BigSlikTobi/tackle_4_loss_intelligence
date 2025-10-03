"""Writer implementations for dataset pipelines."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ...core.db.database_init import get_supabase_client
from ...core.utils.logging import get_logger

from .base import PipelineResult


class SupabaseWriter:
    """Persist transformed records into a Supabase table."""

    def __init__(
        self,
        table_name: str,
        *,
        conflict_columns: Optional[Sequence[str]] = None,
        clear_column: Optional[str] = None,
        clear_guard: Any = "",
        supabase_client: Any = None,
    ) -> None:
        self.table_name = table_name
        self.conflict_columns = list(conflict_columns) if conflict_columns else []
        self.clear_column = clear_column
        self.clear_guard = clear_guard
        self.client = supabase_client or get_supabase_client()
        if not self.client:
            raise RuntimeError("Supabase client is not available; cannot write records")
        self.logger = get_logger(f"SupabaseWriter[{table_name}]")

    def write(self, records: List[Dict[str, Any]], *, clear: bool = False) -> PipelineResult:
        processed = len(records)
        messages: List[str] = []
        try:
            if clear:
                self._clear_table()
                messages.append("Cleared table before write")
            if not records:
                message = "No records to write"
                self.logger.info(message)
                return PipelineResult(True, processed, messages=messages or [message])
            response = self._perform_write(records)
            error = getattr(response, "error", None)
            if error:
                self.logger.error("Supabase error: %s", error)
                return PipelineResult(False, processed, error=str(error))
            written = len(getattr(response, "data", []) or [])
            if not written:
                written = processed
            if messages:
                return PipelineResult(True, processed, written=written, messages=messages)
            return PipelineResult(True, processed, written=written)
        except Exception as exc:  # pragma: no cover - safety net
            self.logger.exception("Failed to write records to %s", self.table_name)
            return PipelineResult(False, processed, error=str(exc))

    def _perform_write(self, records: List[Dict[str, Any]]) -> Any:
        table = self.client.table(self.table_name)
        if self.conflict_columns:
            conflict = ",".join(self.conflict_columns)
            self.logger.debug("Upserting %d records with conflict cols: %s", len(records), conflict)
            return table.upsert(records, on_conflict=conflict).execute()
        self.logger.debug("Inserting %d records", len(records))
        return table.insert(records).execute()

    def _clear_table(self) -> None:
        table = self.client.table(self.table_name).delete()
        if self.clear_column:
            table = table.neq(self.clear_column, self.clear_guard)
        response = table.execute()
        error = getattr(response, "error", None)
        if error:
            raise RuntimeError(f"Failed to clear {self.table_name}: {error}")
        self.logger.debug("Cleared table %s", self.table_name)


class NullWriter:
    """Writer that skips persistence but returns a successful result.
    For dry runs or testing pipelines without database side effects.
    """

    def write(self, records: List[Dict[str, Any]], *, clear: bool = False) -> PipelineResult:
        message = "Writer disabled; skipping persistence"
        return PipelineResult(True, len(records), messages=[message])
