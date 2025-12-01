"""End-to-end batch pipeline for fact extraction."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import openai

from .request_generator import FactsBatchRequestGenerator, GeneratedBatch
from .result_processor import FactsBatchResultProcessor

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


class FactsBatchPipeline:
    """Create and submit OpenAI batch jobs for fact extraction.
    
    Provides end-to-end workflow for batch fact extraction:
    - Generate JSONL request files from pending articles
    - Upload and submit to OpenAI Batch API
    - Check batch status
    - Download and process completed results
    
    Example:
        pipeline = FactsBatchPipeline()
        
        # Create batch job
        result = pipeline.create_batch(limit=500)
        
        # Check status periodically
        status = pipeline.check_status(result.batch_id)
        
        # When complete, process results
        if status["status"] == "completed":
            summary = pipeline.process_batch(result.batch_id)
    """

    def __init__(
        self,
        *,
        generator: Optional[FactsBatchRequestGenerator] = None,
        processor: Optional[FactsBatchResultProcessor] = None,
        api_key: Optional[str] = None,
        embedding_api_key: Optional[str] = None,
        output_dir: Optional[Path] = None,
        model: str = "gpt-5-nano",
    ) -> None:
        """Initialize batch pipeline.
        
        Args:
            generator: Custom request generator
            processor: Custom result processor
            api_key: OpenAI API key
            embedding_api_key: API key for embeddings
            output_dir: Directory for batch files
            model: Model for fact extraction
        """
        self.output_dir = output_dir or Path("./batch_files")
        self.output_dir.mkdir(exist_ok=True)

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.embedding_api_key = embedding_api_key or self.api_key

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for batch creation")

        openai.api_key = self.api_key
        self.model = model

        self.generator = generator or FactsBatchRequestGenerator(
            model=model,
            output_dir=self.output_dir,
        )
        self.processor = processor or FactsBatchResultProcessor(
            embedding_api_key=self.embedding_api_key,
        )

    def create_batch(
        self,
        *,
        limit: Optional[int] = None,
        skip_existing: bool = True,
        high_fact_count_threshold: Optional[int] = None,
        include_unextracted: bool = True,
        max_age_hours: Optional[int] = None,
    ) -> BatchCreationResult:
        """Generate requests, upload them, and create the OpenAI batch job.
        
        Args:
            limit: Maximum articles to include
            skip_existing: Skip articles that already have facts
            high_fact_count_threshold: If set, only include articles with facts_count > threshold
            include_unextracted: Include articles without content_extracted_at set.
                                 When True (default), processes any article directly.
                                 When False, only processes pre-validated articles.
            
        Returns:
            BatchCreationResult with batch ID and metadata
        """
        # Generate JSONL file
        batch_payload: GeneratedBatch = self.generator.generate(
            limit=limit,
            skip_existing=skip_existing,
            high_fact_count_threshold=high_fact_count_threshold,
            include_unextracted=include_unextracted,
            max_age_hours=max_age_hours,
        )

        # Upload to OpenAI
        with batch_payload.file_path.open("rb") as handle:
            uploaded = openai.files.create(file=handle, purpose="batch")

        # Create batch job
        batch = openai.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={
                "type": "facts_extraction",
                "timestamp": batch_payload.metadata.get(
                    "timestamp", datetime.now(timezone.utc).isoformat()
                ),
                "requests": str(batch_payload.total_requests),
                "articles": str(batch_payload.total_articles),
                "model": self.model,
            },
        )

        # Save batch info locally
        batch_info = {
            "batch_id": batch.id,
            "status": batch.status,
            "input_file_id": uploaded.id,
            "input_file_path": str(batch_payload.file_path),
            "metadata_path": str(batch_payload.metadata_path),
            "model": self.model,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "total_requests": batch_payload.total_requests,
            "total_articles": batch_payload.total_articles,
        }

        batch_info_path = self.output_dir / f"facts_batch_{batch.id}.json"
        with batch_info_path.open("w") as handle:
            json.dump(batch_info, handle, indent=2)

        logger.info(
            "Created facts batch",
            extra={
                "batch_id": batch.id,
                "status": batch.status,
                "requests": batch_payload.total_requests,
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
        """Retrieve batch status from OpenAI.
        
        Args:
            batch_id: The batch ID to check
            
        Returns:
            Status dict with batch information
        """
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
        skip_existing: bool = True,
        create_embeddings: bool = True,
        force_delete: bool = False,
    ) -> dict:
        """Download a completed batch output and write results to the database.
        
        Args:
            batch_id: The batch ID to process
            dry_run: If True, don't write to database
            skip_existing: Skip articles that already have facts
            create_embeddings: Create embeddings for new facts
            force_delete: Delete existing facts before inserting (for re-extraction)
            
        Returns:
            Summary dict with processing statistics
        """
        batch = openai.batches.retrieve(batch_id)
        if batch.status != "completed":
            raise ValueError(f"Batch {batch_id} is not completed (status: {batch.status})")

        if not getattr(batch, "output_file_id", None):
            raise ValueError(f"Batch {batch_id} has no output file")

        # Load model from saved batch info
        model = self._load_model_from_metadata(batch_id)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = self.output_dir / f"facts_batch_{batch_id}_output_{timestamp}.jsonl"

        # Download output file
        logger.info("Downloading output file %s", batch.output_file_id)
        output_content = openai.files.content(batch.output_file_id)
        output_text = output_content.text
        with output_path.open("w") as handle:
            handle.write(output_text)

        # Download error file if present
        error_path = None
        if getattr(batch, "error_file_id", None):
            logger.info("Downloading error file %s", batch.error_file_id)
            error_content = openai.files.content(batch.error_file_id)
            error_text = error_content.text
            error_path = self.output_dir / f"facts_batch_{batch_id}_errors_{timestamp}.jsonl"
            with error_path.open("w") as handle:
                handle.write(error_text)

        # Process the output
        logger.info("Processing output file: %s", output_path)
        result = self.processor.process(
            output_file=output_path,
            model=model,
            dry_run=dry_run,
            skip_existing=skip_existing,
            create_embeddings=create_embeddings,
            force_delete=force_delete,
        )

        # Save summary
        summary = {
            "batch_id": batch_id,
            "status": batch.status,
            "output_path": str(output_path),
            "error_path": str(error_path) if error_path else None,
            "articles_in_output": result.articles_in_output,
            "articles_processed": result.articles_processed,
            "articles_skipped_existing": result.articles_skipped_existing,
            "articles_skipped_no_facts": result.articles_skipped_no_facts,
            "articles_with_errors": result.articles_with_errors,
            "facts_extracted": result.facts_extracted,
            "facts_filtered": result.facts_filtered,
            "facts_written": result.facts_written,
            "embeddings_created": result.embeddings_created,
            "errors": result.errors[:50],  # Limit errors in summary
            "dry_run": dry_run,
        }

        summary_path = self.output_dir / f"facts_batch_{batch_id}_summary_{timestamp}.json"
        with summary_path.open("w") as handle:
            json.dump(summary, handle, indent=2)

        logger.info("Facts batch processing complete for %s", batch_id)
        return summary

    def list_batches(self, limit: int = 20) -> list:
        """List recent batch jobs.
        
        Args:
            limit: Maximum number of batches to return
            
        Returns:
            List of batch info dicts
        """
        batches = openai.batches.list(limit=limit)
        
        result = []
        for batch in batches.data:
            # Filter to only facts extraction batches
            metadata = getattr(batch, "metadata", {}) or {}
            if metadata.get("type") != "facts_extraction":
                continue
                
            info = {
                "batch_id": batch.id,
                "status": batch.status,
                "created_at": getattr(batch, "created_at", None),
                "model": metadata.get("model", "unknown"),
            }
            if hasattr(batch, "request_counts") and batch.request_counts:
                total = batch.request_counts.total
                completed = batch.request_counts.completed
                info["progress"] = f"{completed}/{total}"
            result.append(info)
            
        return result

    def cancel_batch(self, batch_id: str) -> dict:
        """Cancel a running batch job.
        
        Args:
            batch_id: The batch ID to cancel
            
        Returns:
            Updated status dict
        """
        batch = openai.batches.cancel(batch_id)
        return {
            "batch_id": batch.id,
            "status": batch.status,
        }

    def _load_model_from_metadata(self, batch_id: str) -> str:
        """Load model from stored batch metadata."""
        # Try to find batch info file
        for path in self.output_dir.glob(f"facts_batch_{batch_id}.json"):
            try:
                with path.open("r") as handle:
                    data = json.load(handle)
                    return data.get("model", self.model)
            except Exception:
                pass

        return self.model
