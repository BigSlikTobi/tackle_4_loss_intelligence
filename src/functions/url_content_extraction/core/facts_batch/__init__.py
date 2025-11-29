"""Batch processing module for fact extraction using OpenAI Batch API.

Provides 50% cost savings for processing large article backlogs by using
the OpenAI Batch API with 24h completion window.

Components:
- FactsBatchRequestGenerator: Generate JSONL batch request files
- FactsBatchResultProcessor: Process completed batch outputs
- FactsBatchPipeline: End-to-end batch creation and processing

Usage:
    from src.functions.url_content_extraction.core.facts_batch import FactsBatchPipeline
    
    pipeline = FactsBatchPipeline()
    
    # Create batch job
    result = pipeline.create_batch(limit=500)
    print(f"Batch {result.batch_id} created with {result.total_requests} requests")
    
    # Check status
    status = pipeline.check_status(result.batch_id)
    
    # Process completed batch
    if status["status"] == "completed":
        summary = pipeline.process_batch(result.batch_id)
"""

from .request_generator import FactsBatchRequestGenerator, GeneratedBatch
from .result_processor import FactsBatchResultProcessor, ProcessingResult
from .pipeline import FactsBatchPipeline, BatchCreationResult

__all__ = [
    "FactsBatchRequestGenerator",
    "GeneratedBatch",
    "FactsBatchResultProcessor",
    "ProcessingResult",
    "FactsBatchPipeline",
    "BatchCreationResult",
]
