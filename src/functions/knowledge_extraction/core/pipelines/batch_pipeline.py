"""
Orchestrates batch processing pipeline for knowledge extraction.

Coordinates: request generation, upload, batch creation, status monitoring, 
result download, and processing.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

import openai

from ..batch.request_generator import BatchRequestGenerator
from ..batch.result_processor import BatchResultProcessor

logger = logging.getLogger(__name__)


class BatchPipeline:
    """
    Orchestrates the complete batch processing workflow.
    
    Steps:
    1. Generate batch request file (.jsonl)
    2. Upload file to OpenAI
    3. Create batch job
    4. Poll for completion (or return for later monitoring)
    5. Download results
    6. Process results and write to database
    """
    
    def __init__(
        self,
        generator: Optional[BatchRequestGenerator] = None,
        processor: Optional[BatchResultProcessor] = None,
        api_key: Optional[str] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize the batch pipeline.
        
        Args:
            generator: Batch request generator (default: new instance)
            processor: Batch result processor (default: new instance)
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            output_dir: Directory for batch files (default: ./batch_files)
        """
        self.generator = generator or BatchRequestGenerator(output_dir=output_dir)
        self.processor = processor or BatchResultProcessor()
        self.output_dir = output_dir or Path("./batch_files")
        
        # Initialize OpenAI client
        import os
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required (set OPENAI_API_KEY env var)")
        
        openai.api_key = self.api_key
        
        logger.info("Initialized BatchPipeline")
    
    def create_batch(
        self,
        limit: Optional[int] = None,
        retry_failed: bool = False,
        max_error_count: int = 3,
        wait_for_completion: bool = False,
        poll_interval: int = 60,
    ) -> Dict:
        """
        Create a batch job for knowledge extraction.
        
        Args:
            limit: Maximum number of groups to include (None for all)
            retry_failed: If True, include failed extractions for retry
            max_error_count: Don't retry if error_count exceeds this
            wait_for_completion: If True, wait for batch to complete
            poll_interval: Seconds between status checks (default: 60)
            
        Returns:
            Dict with batch information:
                - batch_id: OpenAI batch ID
                - status: Batch status
                - input_file_id: ID of uploaded input file
                - file_path: Local path to input file
                - metadata: Batch metadata
        """
        logger.info("=" * 80)
        logger.info("Creating Batch Job")
        logger.info("=" * 80)
        
        # Step 1: Generate request file
        logger.info("Step 1: Generating batch request file...")
        gen_result = self.generator.generate(
            limit=limit,
            retry_failed=retry_failed,
            max_error_count=max_error_count,
        )
        
        if gen_result["total_requests"] == 0:
            logger.warning("No requests to process")
            return {
                "batch_id": None,
                "status": "no_requests",
                "total_requests": 0,
            }
        
        input_file_path = gen_result["file_path"]
        metadata = gen_result["metadata"]
        
        # Step 2: Upload file to OpenAI
        logger.info(f"\nStep 2: Uploading file to OpenAI: {input_file_path}")
        
        with open(input_file_path, "rb") as f:
            file_obj = openai.files.create(
                file=f,
                purpose="batch"
            )
        
        logger.info(f"File uploaded with ID: {file_obj.id}")
        
        # Step 3: Create batch
        logger.info(f"\nStep 3: Creating batch job...")
        
        # Determine endpoint - use /v1/responses for GPT-5 models
        endpoint = "/v1/responses"
        
        batch = openai.batches.create(
            input_file_id=file_obj.id,
            endpoint=endpoint,
            completion_window="24h",
            metadata={
                "description": "Knowledge extraction for NFL story groups",
                "total_groups": str(metadata["total_groups"]),
                "timestamp": metadata["timestamp"],
            }
        )
        
        logger.info(f"Batch created with ID: {batch.id}")
        logger.info(f"Status: {batch.status}")
        logger.info(f"Endpoint: {endpoint}")
        
        # Save batch info
        batch_info = {
            "batch_id": batch.id,
            "status": batch.status,
            "input_file_id": file_obj.id,
            "input_file_path": input_file_path,
            "metadata_path": gen_result["metadata_path"],
            "endpoint": endpoint,
            "created_at": datetime.now().isoformat(),
            "total_requests": gen_result["total_requests"],
            "total_groups": gen_result["total_groups"],
            "metadata": metadata,
        }
        
        batch_info_path = self.output_dir / f"batch_{batch.id}_info.json"
        with open(batch_info_path, "w") as f:
            json.dump(batch_info, f, indent=2)
        
        logger.info(f"\nBatch info saved: {batch_info_path}")
        
        logger.info("=" * 80)
        logger.info("Batch Job Created Successfully")
        logger.info("=" * 80)
        logger.info(f"Batch ID: {batch.id}")
        logger.info(f"Status: {batch.status}")
        logger.info(f"Total groups: {gen_result['total_groups']}")
        logger.info(f"Total requests: {gen_result['total_requests']}")
        logger.info(f"\nTo check status later, run:")
        logger.info(f"  python extract_knowledge_cli.py --batch-status {batch.id}")
        logger.info("=" * 80)
        
        # Optionally wait for completion
        if wait_for_completion:
            logger.info(f"\nWaiting for batch to complete (checking every {poll_interval}s)...")
            batch_info = self.wait_for_completion(batch.id, poll_interval)
            
            # If completed, automatically process results
            if batch_info["status"] == "completed":
                logger.info("\nBatch completed! Processing results...")
                process_result = self.process_batch(batch.id)
                batch_info["processing_result"] = process_result
        
        return batch_info
    
    def wait_for_completion(
        self,
        batch_id: str,
        poll_interval: int = 60,
        max_wait: int = 86400,  # 24 hours
    ) -> Dict:
        """
        Wait for a batch to complete.
        
        Args:
            batch_id: OpenAI batch ID
            poll_interval: Seconds between status checks
            max_wait: Maximum seconds to wait (default: 24 hours)
            
        Returns:
            Dict with final batch status
        """
        start_time = time.time()
        last_status = None
        
        while True:
            elapsed = time.time() - start_time
            
            if elapsed > max_wait:
                logger.warning(f"Max wait time ({max_wait}s) exceeded")
                break
            
            # Check status
            batch = openai.batches.retrieve(batch_id)
            
            if batch.status != last_status:
                logger.info(f"Batch status: {batch.status}")
                last_status = batch.status
                
                # Show progress if available
                if hasattr(batch, 'request_counts') and batch.request_counts:
                    counts = batch.request_counts
                    logger.info(
                        f"  Progress: {counts.completed}/{counts.total} "
                        f"(failed: {counts.failed})"
                    )
            
            # Check if terminal state reached
            if batch.status in ["completed", "failed", "expired", "cancelled"]:
                logger.info(f"Batch reached terminal state: {batch.status}")
                
                # Convert request_counts to dict if present
                request_counts_dict = None
                if hasattr(batch, 'request_counts') and batch.request_counts:
                    request_counts_dict = {
                        "total": batch.request_counts.total,
                        "completed": batch.request_counts.completed,
                        "failed": batch.request_counts.failed,
                    }
                
                return {
                    "batch_id": batch.id,
                    "status": batch.status,
                    "output_file_id": getattr(batch, 'output_file_id', None),
                    "error_file_id": getattr(batch, 'error_file_id', None),
                    "request_counts": request_counts_dict,
                }
            
            # Wait before next check
            time.sleep(poll_interval)
        
        # Timeout - return current status
        batch = openai.batches.retrieve(batch_id)
        return {
            "batch_id": batch.id,
            "status": batch.status,
            "timed_out": True,
        }
    
    def check_status(self, batch_id: str) -> Dict:
        """
        Check the status of a batch job.
        
        Args:
            batch_id: OpenAI batch ID
            
        Returns:
            Dict with batch status information
        """
        logger.info(f"Checking status for batch: {batch_id}")
        
        batch = openai.batches.retrieve(batch_id)
        
        status_info = {
            "batch_id": batch.id,
            "status": batch.status,
            "created_at": batch.created_at,
            "expires_at": getattr(batch, 'expires_at', None),
            "completed_at": getattr(batch, 'completed_at', None),
            "failed_at": getattr(batch, 'failed_at', None),
            "output_file_id": getattr(batch, 'output_file_id', None),
            "error_file_id": getattr(batch, 'error_file_id', None),
        }
        
        # Add request counts if available
        if hasattr(batch, 'request_counts') and batch.request_counts:
            status_info["request_counts"] = {
                "total": batch.request_counts.total,
                "completed": batch.request_counts.completed,
                "failed": batch.request_counts.failed,
            }
        
        # Load local batch info if available
        batch_info_path = self.output_dir / f"batch_{batch_id}_info.json"
        if batch_info_path.exists():
            with open(batch_info_path, "r") as f:
                local_info = json.load(f)
                status_info["local_info"] = local_info
        
        return status_info
    
    def process_batch(
        self,
        batch_id: str,
        dry_run: bool = False,
    ) -> Dict:
        """
        Process completed batch results.
        
        Args:
            batch_id: OpenAI batch ID
            dry_run: If True, don't write to database
            
        Returns:
            Dict with processing results
        """
        logger.info("=" * 80)
        logger.info(f"Processing Batch Results: {batch_id}")
        logger.info("=" * 80)
        
        # Check batch status
        batch = openai.batches.retrieve(batch_id)
        
        if batch.status != "completed":
            raise ValueError(
                f"Batch is not completed (status: {batch.status}). "
                "Wait for completion before processing."
            )
        
        if not batch.output_file_id:
            raise ValueError("Batch has no output file")
        
        # Download output file
        logger.info(f"Downloading output file: {batch.output_file_id}")
        
        output_content = openai.files.content(batch.output_file_id)
        output_text = output_content.text
        
        # Save to local file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = self.output_dir / f"batch_{batch_id}_output_{timestamp}.jsonl"
        
        with open(output_path, "w") as f:
            f.write(output_text)
        
        logger.info(f"Output saved to: {output_path}")
        
        # Download error file if exists
        if batch.error_file_id:
            logger.info(f"Downloading error file: {batch.error_file_id}")
            
            error_content = openai.files.content(batch.error_file_id)
            error_text = error_content.text
            
            error_path = self.output_dir / f"batch_{batch_id}_errors_{timestamp}.jsonl"
            with open(error_path, "w") as f:
                f.write(error_text)
            
            logger.info(f"Errors saved to: {error_path}")
        
        # Process results
        logger.info("\nProcessing results and writing to database...")
        result = self.processor.process(output_path, dry_run=dry_run)
        
        # Save processing summary
        summary = {
            "batch_id": batch_id,
            "processed_at": timestamp,
            "output_file_path": str(output_path),
            "dry_run": dry_run,
            "results": {
                "groups_processed": result.groups_processed,
                "topics_extracted": result.topics_extracted,
                "entities_extracted": result.entities_extracted,
                "groups_with_errors": result.groups_with_errors,
                "error_count": len(result.errors),
            }
        }
        
        summary_path = self.output_dir / f"batch_{batch_id}_summary_{timestamp}.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"\nSummary saved: {summary_path}")
        
        return {
            "batch_id": batch_id,
            "output_path": str(output_path),
            "summary_path": str(summary_path),
            "groups_processed": result.groups_processed,
            "topics_extracted": result.topics_extracted,
            "entities_extracted": result.entities_extracted,
            "groups_with_errors": result.groups_with_errors,
            "errors": result.errors,
        }
    
    def cancel_batch(self, batch_id: str) -> Dict:
        """
        Cancel a running batch job.
        
        Args:
            batch_id: OpenAI batch ID
            
        Returns:
            Dict with cancellation status
        """
        logger.info(f"Cancelling batch: {batch_id}")
        
        batch = openai.batches.cancel(batch_id)
        
        logger.info(f"Batch status: {batch.status}")
        
        return {
            "batch_id": batch.id,
            "status": batch.status,
        }
    
    def list_batches(self, limit: int = 10) -> List[Dict]:
        """
        List recent batch jobs.
        
        Args:
            limit: Maximum number of batches to list
            
        Returns:
            List of batch info dicts
        """
        logger.info(f"Listing recent batches (limit: {limit})")
        
        batches_list = openai.batches.list(limit=limit)
        
        results = []
        for batch in batches_list.data:
            info = {
                "batch_id": batch.id,
                "status": batch.status,
                "created_at": batch.created_at,
            }
            
            if hasattr(batch, 'request_counts') and batch.request_counts:
                info["progress"] = (
                    f"{batch.request_counts.completed}/"
                    f"{batch.request_counts.total}"
                )
            
            results.append(info)
        
        return results
