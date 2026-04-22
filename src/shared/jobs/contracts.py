"""Generic job-state contracts shared by extraction services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class JobError:
    """Terminal error payload stored on the job row."""

    code: str
    message: str
    retryable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass
class SupabaseConfig:
    """Per-request Supabase credentials for the ephemeral job store."""

    url: str
    key: str
    jobs_table: str = "extraction_jobs"
