"""End-to-end batch creation for topic summary generation."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import openai

from .request_generator import SummaryBatchRequestGenerator, GeneratedBatch, SummaryTask
from .result_processor import SummaryBatchResultProcessor

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
    total_articles: int


class SummaryBatchPipeline:
    """Create and submit OpenAI batch jobs for summary generation."""

    def __init__(
        self,
        *,
        generator: Optional[SummaryBatchRequestGenerator] = None,
        processor: Optional[SummaryBatchResultProcessor] = None,
        api_key: Optional[str] = None,
        embedding_api_key: Optional[str] = None,
        output_dir: Optional[Path] = None,
    ) -> None:
        self.output_dir = output_dir or Path("./batch_files")
        self.output_dir.mkdir(exist_ok=True)
        
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.embedding_api_key = embedding_api_key or self.api_key
        
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for batch creation")

        openai.api_key = self.api_key
        
        self.generator = generator or SummaryBatchRequestGenerator(output_dir=self.output_dir)
        self.processor = processor or SummaryBatchResultProcessor(
            embedding_api_key=self.embedding_api_key
        )

    def create_batch(
        self,
        *,
        task: SummaryTask = "all",
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
                "articles": str(batch_payload.total_articles),
            },
        )

        batch_info = {
            "batch_id": batch.id,
            "status": batch.status,
            "input_file_id": uploaded.id,
            "input_file_path": str(batch_payload.file_path),
            "metadata_path": str(batch_payload.metadata_path),
            "task": task,
            "model": self.generator.model,
            "created_at": datetime.utcnow().isoformat(),
        }

        batch_info_path = self.output_dir / f"summary_batch_{batch.id}.json"
        with batch_info_path.open("w") as handle:
            json.dump(batch_info, handle, indent=2)

        logger.info(
            "Created summary batch",
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
            total_articles=batch_payload.total_articles,
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
        dry_run: bool = False,
        skip_existing: bool = False,
        create_embeddings: bool = True,
    ) -> dict:
        """Download a completed batch output and write results to the database."""

        batch = openai.batches.retrieve(batch_id)
        if batch.status != "completed":
            raise ValueError(f"Batch {batch_id} is not completed (status: {batch.status})")

        if not getattr(batch, "output_file_id", None):
            raise ValueError(f"Batch {batch_id} has no output file")

        # Load metadata to get model info
        model = self._load_model_from_metadata(batch_id)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = self.output_dir / f"summary_batch_{batch_id}_output_{timestamp}.jsonl"

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
            error_path = self.output_dir / f"summary_batch_{batch_id}_errors_{timestamp}.jsonl"
            with error_path.open("w") as handle:
                handle.write(error_text)

        logger.info("Processing output file: %s", output_path)
        result = self.processor.process(
            output_file=output_path,
            model=model,
            dry_run=dry_run,
            skip_existing=skip_existing,
            create_embeddings=create_embeddings,
        )

        summary = {
            "batch_id": batch_id,
            "status": batch.status,
            "output_path": str(output_path),
            "error_path": str(error_path) if error_path else None,
            "articles_in_output": result.articles_in_output,
            "articles_processed": result.articles_processed,
            "articles_skipped_existing": result.articles_skipped_existing,
            "articles_skipped_no_data": result.articles_skipped_no_data,
            "summaries_written": result.summaries_written,
            "topic_summaries_written": result.topic_summaries_written,
            "embeddings_created": result.embeddings_created,
            "errors": result.errors,
            "dry_run": dry_run,
        }

        summary_path = self.output_dir / f"summary_batch_{batch_id}_summary_{timestamp}.json"
        with summary_path.open("w") as handle:
            json.dump(summary, handle, indent=2)

        logger.info("Summary batch processing complete for %s", batch_id)
        return summary

    def _load_model_from_metadata(self, batch_id: str) -> str:
        """Load model from stored batch metadata."""

        # Try to find metadata file
        for path in self.output_dir.glob(f"summary_batch_{batch_id}.json"):
            try:
                with path.open("r") as handle:
                    data = json.load(handle)
                    return data.get("model", "gpt-5-nano")
            except Exception:
                pass
        
        # Also check original batch files
        for path in self.output_dir.glob("summary_batch_*_metadata.json"):
            try:
                with path.open("r") as handle:
                    data = json.load(handle)
                    if data.get("model"):
                        return data["model"]
            except Exception:
                pass

        return "gpt-5-nano"  # Default
