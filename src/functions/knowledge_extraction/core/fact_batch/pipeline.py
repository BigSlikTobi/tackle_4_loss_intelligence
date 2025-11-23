"""End-to-end batch creation for fact-level knowledge extraction."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import openai

from .request_generator import FactBatchRequestGenerator, GeneratedBatch, KnowledgeTask

logger = logging.getLogger(__name__)


@dataclass
class BatchCreationResult:
    """Summary of the batch job creation."""

    batch_id: Optional[str]
    status: str
    input_file_id: Optional[str]
    input_file_path: Optional[str]
    metadata_path: Optional[str]
    total_requests: int
    total_facts: int


class FactBatchPipeline:
    """Create and submit OpenAI batch jobs for fact-level knowledge tasks."""

    def __init__(
        self,
        *,
        generator: Optional[FactBatchRequestGenerator] = None,
        api_key: Optional[str] = None,
        output_dir: Optional[Path] = None,
    ) -> None:
        self.generator = generator or FactBatchRequestGenerator(output_dir=output_dir)
        self.output_dir = output_dir or Path("./batch_files")

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for batch creation")

        openai.api_key = self.api_key

    def create_batch(
        self,
        *,
        task: KnowledgeTask,
        limit: Optional[int] = None,
    ) -> BatchCreationResult:
        """Generate requests, upload them, and create the OpenAI batch job."""

        batch_payload: GeneratedBatch = self.generator.generate(task=task, limit=limit)

        with batch_payload.file_path.open("rb") as handle:
            uploaded = openai.files.create(file=handle, purpose="batch")

        batch = openai.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={
                "task": task,
                "timestamp": batch_payload.metadata.get("timestamp", datetime.utcnow().isoformat()),
                "requests": str(batch_payload.total_requests),
            },
        )

        batch_info = {
            "batch_id": batch.id,
            "status": batch.status,
            "input_file_id": uploaded.id,
            "input_file_path": str(batch_payload.file_path),
            "metadata_path": str(batch_payload.metadata_path),
            "task": task,
            "created_at": datetime.utcnow().isoformat(),
        }

        batch_info_path = self.output_dir / f"fact_knowledge_batch_{batch.id}.json"
        with batch_info_path.open("w") as handle:
            json.dump(batch_info, handle, indent=2)

        logger.info(
            "Created fact knowledge batch",
            extra={
                "batch_id": batch.id,
                "status": batch.status,
                "input_file": str(batch_payload.file_path),
            },
        )

        return BatchCreationResult(
            batch_id=batch.id,
            status=batch.status,
            input_file_id=uploaded.id,
            input_file_path=str(batch_payload.file_path),
            metadata_path=str(batch_payload.metadata_path),
            total_requests=batch_payload.total_requests,
            total_facts=batch_payload.total_facts,
        )
