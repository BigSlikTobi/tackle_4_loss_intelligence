"""
OpenAI embedding client for generating text embeddings.

Uses OpenAI's text-embedding-3-small model with rate limiting and error handling.
Production-ready with timeout handling, connection pooling, and comprehensive error recovery.
"""

import logging
import time
import os
from typing import Optional

from openai import OpenAI, RateLimitError, APIError, APITimeoutError, APIConnectionError

from src.shared.utils.env import load_env

logger = logging.getLogger(__name__)

# Load environment variables
load_env()


class OpenAIEmbeddingClient:
    """
    Production-ready client for generating embeddings using OpenAI's API.

    Features:
    - text-embedding-3-small model (1536 dimensions)
    - Rate limiting with token-based throttling
    - Automatic retry logic with exponential backoff
    - Timeout handling and connection error recovery
    - Batch processing support
    - Cost tracking and monitoring
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        max_retries: int = 3,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        max_tokens_per_minute: Optional[int] = None,
    ):
        """
        Initialize the OpenAI embedding client.

        Args:
            model: OpenAI embedding model to use
            max_retries: Maximum retry attempts for failed requests
            api_key: OpenAI API key (if not provided, loads from env)
            timeout: Request timeout in seconds (default: 30.0)
            max_tokens_per_minute: Optional rate limit for tokens per minute
        """
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        self.max_tokens_per_minute = max_tokens_per_minute
        
        # Get API key from parameter or environment
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAI API key not found. Set OPENAI_API_KEY in environment or pass to constructor."
            )
        
        # Initialize client with timeout and connection pooling
        self.client = OpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=0,  # We handle retries manually for better control
        )
        
        # Track usage statistics
        self.total_tokens = 0
        self.total_requests = 0
        self.failed_requests = 0
        
        # Rate limiting
        self.tokens_this_minute = 0
        self.minute_start_time = time.time()
        
        logger.info(
            f"Initialized OpenAIEmbeddingClient: model={model}, "
            f"timeout={timeout}s, max_retries={max_retries}"
        )

    def _enforce_rate_limit(self):
        """
        Enforce rate limiting if max_tokens_per_minute is set.
        
        Implements a sliding window rate limiter to prevent hitting API rate limits.
        """
        if not self.max_tokens_per_minute:
            return
        
        current_time = time.time()
        time_since_start = current_time - self.minute_start_time
        
        # Reset counter every minute
        if time_since_start >= 60:
            self.tokens_this_minute = 0
            self.minute_start_time = current_time
            return
        
        # Check if we're over the limit
        if self.tokens_this_minute >= self.max_tokens_per_minute:
            sleep_time = 60 - time_since_start
            if sleep_time > 0:
                logger.info(
                    f"Rate limit reached ({self.tokens_this_minute} tokens), "
                    f"sleeping for {sleep_time:.1f}s"
                )
                time.sleep(sleep_time)
                self.tokens_this_minute = 0
                self.minute_start_time = time.time()

    def generate_embedding(self, text: str) -> dict:
        """
        Generate an embedding vector for a single text.

        Args:
            text: Text to embed

        Returns:
            Dictionary containing:
                - embedding: List of floats (1536 dimensions)
                - model: Model used
                - tokens_used: Number of tokens consumed
                - processing_time: Time taken in seconds

        Raises:
            Exception: If embedding generation fails after retries
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        # Rate limiting check
        self._enforce_rate_limit()

        start_time = time.time()
        last_error = None
        
        # Retry logic with exponential backoff
        for attempt in range(self.max_retries):
            try:
                response = self.client.embeddings.create(
                    input=text,
                    model=self.model
                )
                
                # Extract embedding
                embedding = response.data[0].embedding
                tokens_used = response.usage.total_tokens
                
                # Update statistics
                self.total_tokens += tokens_used
                self.total_requests += 1
                
                # Update rate limiting counter
                if self.max_tokens_per_minute:
                    self.tokens_this_minute += tokens_used
                
                processing_time = time.time() - start_time
                
                logger.debug(
                    f"Generated embedding: {len(embedding)} dimensions, "
                    f"{tokens_used} tokens, {processing_time:.2f}s"
                )
                
                return {
                    "embedding": embedding,
                    "model": self.model,
                    "tokens_used": tokens_used,
                    "processing_time": processing_time,
                }
                
            except RateLimitError as e:
                error_msg = f"Rate limit hit (attempt {attempt + 1}/{self.max_retries}): {e}"
                logger.warning(error_msg)
                last_error = e
                self.failed_requests += 1
                
                if attempt < self.max_retries - 1:
                    # Exponential backoff: 2s, 4s, 8s...
                    sleep_time = 2 ** (attempt + 1)
                    logger.info(f"Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                else:
                    raise Exception(f"Rate limit exceeded after {self.max_retries} attempts") from e

            except APITimeoutError as e:
                error_msg = f"Request timeout (attempt {attempt + 1}/{self.max_retries}): {e}"
                logger.warning(error_msg)
                last_error = e
                self.failed_requests += 1
                
                if attempt < self.max_retries - 1:
                    sleep_time = 2 ** attempt
                    logger.info(f"Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                else:
                    raise Exception(f"Request timeout after {self.max_retries} attempts") from e

            except APIConnectionError as e:
                error_msg = f"Connection error (attempt {attempt + 1}/{self.max_retries}): {e}"
                logger.warning(error_msg)
                last_error = e
                self.failed_requests += 1
                
                if attempt < self.max_retries - 1:
                    sleep_time = 2 ** (attempt + 1)  # Longer wait for connection issues
                    logger.info(f"Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                else:
                    raise Exception(f"Connection error after {self.max_retries} attempts") from e
                    
            except APIError as e:
                error_msg = f"OpenAI API error (attempt {attempt + 1}/{self.max_retries}): {e}"
                logger.warning(error_msg)
                last_error = e
                self.failed_requests += 1
                
                if attempt < self.max_retries - 1:
                    sleep_time = 2 ** attempt
                    logger.info(f"Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                else:
                    raise Exception(f"API error after {self.max_retries} attempts") from e
                    
            except Exception as e:
                logger.error(f"Unexpected error generating embedding: {e}", exc_info=True)
                self.failed_requests += 1
                raise

    def generate_embeddings_batch(self, texts: list[str]) -> list[dict]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of dictionaries, each containing:
                - embedding: List of floats
                - model: Model used
                - tokens_used: Tokens for this text
                - processing_time: Time taken
        """
        if not texts:
            return []
        
        logger.info(f"Generating embeddings for {len(texts)} texts...")
        
        results = []
        for i, text in enumerate(texts, 1):
            try:
                result = self.generate_embedding(text)
                results.append(result)
                logger.debug(f"Generated embedding {i}/{len(texts)}")
            except Exception as e:
                logger.error(f"Failed to generate embedding {i}/{len(texts)}: {e}")
                # Continue with next text instead of failing entire batch
                results.append({
                    "embedding": None,
                    "model": self.model,
                    "tokens_used": 0,
                    "processing_time": 0,
                    "error": str(e),
                })
        
        logger.info(f"Completed batch: {len([r for r in results if r.get('embedding')])} successful")
        return results

    def get_usage_stats(self) -> dict:
        """
        Get usage statistics for this client instance.

        Returns:
            Dictionary with:
                - total_requests: Number of API requests made
                - failed_requests: Number of failed requests
                - total_tokens: Total tokens consumed
                - estimated_cost: Estimated cost in USD (based on current pricing)
        """
        # text-embedding-3-small pricing: $0.00002 per 1K tokens (as of Oct 2024)
        cost_per_1k_tokens = 0.00002
        estimated_cost = (self.total_tokens / 1000) * cost_per_1k_tokens
        
        return {
            "total_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(estimated_cost, 4),
        }

    def reset_stats(self):
        """Reset usage statistics."""
        self.total_tokens = 0
        self.total_requests = 0
        self.failed_requests = 0
        self.tokens_this_minute = 0
        self.minute_start_time = time.time()
        logger.info("Usage statistics reset")
