"""Request models and configuration for URL content extraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.shared.jobs.contracts import SupabaseConfig  # noqa: F401  (re-export)

logger = logging.getLogger(__name__)


MAX_URLS_PER_JOB = 20
MAX_TIMEOUT_SECONDS = 180


@dataclass
class ExtractionOptions:
    """Per-job extraction tuning. Mirrors the legacy module's options block."""

    timeout_seconds: int = 45
    force_playwright: bool = False
    prefer_lightweight: bool = False
    max_paragraphs: int = 120
    min_paragraph_chars: int = 240

    def validate(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("options.timeout_seconds must be > 0")
        if self.timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"options.timeout_seconds must be <= {MAX_TIMEOUT_SECONDS}"
            )
        if self.max_paragraphs < 1:
            raise ValueError("options.max_paragraphs must be >= 1")
        if self.min_paragraph_chars < 0:
            raise ValueError("options.min_paragraph_chars must be >= 0")


@dataclass
class SubmitRequest:
    """Incoming payload for the /submit endpoint."""

    urls: List[str]
    options: ExtractionOptions = field(default_factory=ExtractionOptions)
    supabase: Optional[SupabaseConfig] = None

    def validate(self) -> None:
        if not isinstance(self.urls, list) or not self.urls:
            raise ValueError("urls must be a non-empty list of strings")
        if len(self.urls) > MAX_URLS_PER_JOB:
            raise ValueError(
                f"urls list exceeds the {MAX_URLS_PER_JOB} per-job limit "
                f"(got {len(self.urls)})"
            )
        for entry in self.urls:
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError("every entry in urls must be a non-empty string")
        self.options.validate()
        if self.supabase is None or not self.supabase.url or not self.supabase.key:
            raise ValueError("supabase.url and supabase.key are required")


@dataclass
class PollRequest:
    """Incoming payload for the /poll endpoint."""

    job_id: str
    supabase: Optional[SupabaseConfig] = None

    def validate(self) -> None:
        if not self.job_id:
            raise ValueError("job_id is required")
        if self.supabase is None or not self.supabase.url or not self.supabase.key:
            raise ValueError("supabase.url and supabase.key are required")


@dataclass
class WorkerRequest:
    """Internal payload fired by submit into the worker endpoint."""

    job_id: str
    supabase: Optional[SupabaseConfig] = None

    def validate(self) -> None:
        if not self.job_id:
            raise ValueError("job_id is required")
        if self.supabase is None or not self.supabase.url or not self.supabase.key:
            raise ValueError("supabase.url and supabase.key are required")
