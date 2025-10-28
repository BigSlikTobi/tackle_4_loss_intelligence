"""Error aggregation utilities for the daily team update pipeline."""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecordedError:
    """Structured representation of a captured pipeline error."""

    team_abbr: str
    stage: str
    message: str
    retryable: bool
    exception_type: str
    traceback: Optional[str]


class ErrorHandler:
    """Collects and categorises errors encountered during pipeline execution."""

    def __init__(self) -> None:
        self._errors: List[RecordedError] = []

    def record(self, team_abbr: str, stage: str, exc: BaseException, *, retryable: bool = False) -> None:
        """Record an error for later reporting."""

        exc_type = type(exc).__name__
        tb = "".join(traceback.format_exception(exc)).strip()
        logger.debug("Recording error at stage %s for team %s: %s", stage, team_abbr, exc)
        self._errors.append(
            RecordedError(
                team_abbr=team_abbr,
                stage=stage,
                message=str(exc),
                retryable=retryable,
                exception_type=exc_type,
                traceback=tb if tb else None,
            )
        )

    @property
    def errors(self) -> List[RecordedError]:
        """Return collected error records."""

        return list(self._errors)

    def as_dict(self) -> List[dict]:
        """Serialise errors for JSON responses."""

        return [
            {
                "team_abbr": error.team_abbr,
                "stage": error.stage,
                "message": error.message,
                "retryable": error.retryable,
                "exception_type": error.exception_type,
                "traceback": error.traceback,
            }
            for error in self._errors
        ]
