"""Loader that computes NFL standings and upserts them into Supabase.

Unlike the other loaders, the source of truth is the project's own ``games``
and ``teams`` tables — not an external feed — so this loader sidesteps the
pandas-based ``DatasetPipeline`` and calls :class:`SupabaseWriter` directly.
The public surface mirrors :class:`PipelineLoader` (``load_data`` / ``prepare``)
so the CLI and any future consumers can treat it the same way.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .....core.pipelines import PipelineResult, SupabaseWriter
from .....core.standings.compute import compute_standings_rows
from .....core.utils.logging import get_logger


class StandingsDataLoader:
    """Compute standings rows from ``games`` + ``teams`` and upsert them."""

    name = "standings"

    def __init__(
        self,
        *,
        writer: Optional[SupabaseWriter] = None,
        supabase_client: Any = None,
    ) -> None:
        self._client = supabase_client
        self._writer = writer or SupabaseWriter(
            table_name="standings",
            conflict_columns=["season", "through_week", "team_abbr"],
            supabase_client=supabase_client,
        )
        self._logger = get_logger(f"StandingsDataLoader[{self.name}]")

    def prepare(
        self,
        *,
        season: int,
        through_week: Optional[int] = None,
        **_: Any,
    ) -> List[Dict[str, Any]]:
        """Compute and return the rows that would be written."""
        return compute_standings_rows(
            season=season,
            through_week=through_week,
            client=self._client,
        )

    def load_data(
        self,
        *,
        dry_run: bool = False,
        clear: bool = False,  # accepted for CLI parity; ignored — see note below
        season: int,
        through_week: Optional[int] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        """Compute standings and persist them. Returns a legacy-style dict.

        ``clear`` is accepted but ignored: the conflict-key upsert already
        replaces the prior snapshot for the same ``(season, through_week)``,
        and clearing the entire table would destroy historical snapshots.
        """
        try:
            records = self.prepare(season=season, through_week=through_week)
        except Exception as exc:
            self._logger.exception("Failed to compute standings")
            return PipelineResult(False, 0, error=str(exc)).to_dict()

        processed = len(records)
        if dry_run:
            return PipelineResult(
                True,
                processed,
                messages=[f"Dry run: {processed} standings rows ready"],
            ).to_dict()

        result = self._writer.write(records, clear=False)
        result.processed = processed
        return result.to_dict()

    def inspect(self, **params: Any) -> Dict[str, Any]:
        """Return column metadata for ``--show-columns`` parity."""
        sample = self.prepare(**params)[:1]
        if not sample:
            return {"columns": [], "dtypes": {}, "sample": [], "rowcount": 0}
        columns = list(sample[0].keys())
        dtypes = {col: type(sample[0][col]).__name__ for col in columns}
        return {
            "columns": columns,
            "dtypes": dtypes,
            "sample": sample,
            "rowcount": len(self.prepare(**params)),
        }
