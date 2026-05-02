"""Request models and configuration for the gemini_tts_batch service."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.shared.jobs.contracts import SupabaseConfig  # noqa: F401  (re-export)

from .. import JOB_ACTIONS

logger = logging.getLogger(__name__)


MAX_ITEMS_PER_CREATE = 100


@dataclass
class CreateInput:
    """Input for an ``action='create'`` job."""

    model_name: str
    voice_name: str = "Charon"
    items: List[Dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        if not self.model_name or not self.model_name.strip():
            raise ValueError("model_name is required for action=create")
        if not isinstance(self.items, list) or not self.items:
            raise ValueError("items must be a non-empty list for action=create")
        if len(self.items) > MAX_ITEMS_PER_CREATE:
            raise ValueError(
                f"items list exceeds the {MAX_ITEMS_PER_CREATE} per-job limit "
                f"(got {len(self.items)})"
            )
        seen_ids = set()
        for entry in self.items:
            if not isinstance(entry, dict):
                raise ValueError("every item must be an object")
            item_id = entry.get("id")
            if not isinstance(item_id, str) or not item_id.strip():
                raise ValueError("every item must have a non-empty string id")
            if item_id in seen_ids:
                raise ValueError(f"duplicate item id: {item_id!r}")
            seen_ids.add(item_id)


@dataclass
class StatusInput:
    """Input for an ``action='status'`` job."""

    batch_id: str

    def validate(self) -> None:
        if not self.batch_id or not self.batch_id.strip():
            raise ValueError("batch_id is required for action=status")


@dataclass
class ProcessInput:
    """Input for an ``action='process'`` job.

    The caller chooses the destination bucket and path prefix per request.
    The Supabase storage URL + key are resolved from the worker's env
    (``STORAGE_SUPABASE_URL`` / ``STORAGE_SUPABASE_KEY`` with
    ``SUPABASE_URL`` / ``SUPABASE_SERVICE_ROLE_KEY`` as fallbacks) so secrets
    never travel in request bodies.
    """

    batch_id: str
    bucket: str = "audio"
    path_prefix: str = "gemini-tts-batch"

    def validate(self) -> None:
        if not self.batch_id or not self.batch_id.strip():
            raise ValueError("batch_id is required for action=process")
        if not self.bucket or not self.bucket.strip():
            raise ValueError("storage.bucket must be a non-empty string")
        if not self.path_prefix or not self.path_prefix.strip():
            raise ValueError("storage.path_prefix must be a non-empty string")


@dataclass
class SubmitRequest:
    """Incoming payload for the /submit endpoint."""

    action: str
    create_input: Optional[CreateInput] = None
    status_input: Optional[StatusInput] = None
    process_input: Optional[ProcessInput] = None
    supabase: Optional[SupabaseConfig] = None

    def validate(self) -> None:
        if self.action not in JOB_ACTIONS:
            raise ValueError(
                f"action must be one of: {', '.join(JOB_ACTIONS)}"
            )
        if self.action == "create":
            if self.create_input is None:
                raise ValueError("create payload is required for action=create")
            self.create_input.validate()
        elif self.action == "status":
            if self.status_input is None:
                raise ValueError("status payload is required for action=status")
            self.status_input.validate()
        elif self.action == "process":
            if self.process_input is None:
                raise ValueError("process payload is required for action=process")
            self.process_input.validate()
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
