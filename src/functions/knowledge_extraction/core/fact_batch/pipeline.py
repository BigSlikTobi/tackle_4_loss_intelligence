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
from .result_processor import FactBatchResultProcessor

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
        processor: Optional[FactBatchResultProcessor] = None,
        api_key: Optional[str] = None,
        output_dir: Optional[Path] = None,
    ) -> None:
        self.generator = generator or FactBatchRequestGenerator(output_dir=output_dir)
        self.processor = processor or FactBatchResultProcessor()
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

    def check_status(self, batch_id: str) -> dict:
        """Retrieve batch status from OpenAI."""
        batch = openai.batches.retrieve(batch_id)
        status_info = {
            "batch_id": batch.id,
            "status": batch.status,
            "created_at": getattr(batch, "created_at", None),
            "completed_at": getattr(batch, "completed_at", None),
            "expires_at": getattr(batch, "expires_at", None),
            "output_file_id": getattr(batch, "output_file_id", None),
            "error_file_id": getattr(batch, "error_file_id", None),
        }
        if hasattr(batch, "request_counts") and batch.request_counts:
            status_info["request_counts"] = {
                "total": batch.request_counts.total,
                "completed": batch.request_counts.completed,
                "failed": batch.request_counts.failed,
            }
        return status_info

    def process_batch(
        self,
        batch_id: str,
        *,
        task: KnowledgeTask,
        dry_run: bool = False,
        skip_existing: bool = False,
    ) -> dict:
        """Download a completed batch output and write results to the database."""
        batch = openai.batches.retrieve(batch_id)
        if batch.status != "completed":
            raise ValueError(f"Batch {batch_id} is not completed (status: {batch.status})")

        if not getattr(batch, "output_file_id", None):
            raise ValueError(f"Batch {batch_id} has no output file")

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = self.output_dir / f"fact_batch_{batch_id}_output_{timestamp}.jsonl"

        logger.info("Downloading output file %s", batch.output_file_id)
        output_content = openai.files.content(batch.output_file_id)
        output_text = output_content.text
        with output_path.open("w") as handle:
            handle.write(output_text)

        error_path = None
        if getattr(batch, "error_file_id", None):
            logger.info("Downloading error file %s", batch.error_file_id)
            error_content = openai.files.content(batch.error_file_id)
            error_text = error_content.text
            error_path = self.output_dir / f"fact_batch_{batch_id}_errors_{timestamp}.jsonl"
            with error_path.open("w") as handle:
                handle.write(error_text)

        logger.info("Processing output file: %s", output_path)
        result = self.processor.process(
            output_file=output_path,
            task=task,
            dry_run=dry_run,
            skip_existing=skip_existing,
        )

        summary = {
            "batch_id": batch_id,
            "status": batch.status,
            "output_path": str(output_path),
            "error_path": str(error_path) if error_path else None,
            "facts_in_output": result.facts_in_output,
            "facts_processed": result.facts_processed,
            "facts_skipped_missing": result.facts_skipped_missing,
            "facts_skipped_existing": result.facts_skipped_existing,
            "facts_skipped_no_data": result.facts_skipped_no_data,
            "topics_written": result.topics_written,
            "entities_written": result.entities_written,
            "urls_updated": result.urls_updated,
            "errors": result.errors,
            "missing_fact_ids": result.missing_fact_ids,
            "dry_run": dry_run,
        }

        summary_path = self.output_dir / f"fact_batch_{batch_id}_summary_{timestamp}.json"
        with summary_path.open("w") as handle:
            json.dump(summary, handle, indent=2)

        logger.info("Fact batch processing complete for %s", batch_id)
        return summary
