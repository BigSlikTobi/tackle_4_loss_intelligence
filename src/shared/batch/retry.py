"""Retry decorator for network operations with exponential backoff."""

from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_on_network_error(
    func: Callable[[], T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
) -> T:
    """Retry a function on network/protocol errors with exponential backoff.

    Catches common network errors from httpx/httpcore and retries with
    exponentially increasing delays.

    Args:
        func: Callable to retry (should take no arguments)
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds (doubles each retry)

    Returns:
        Function result

    Raises:
        Exception: Last exception if all retries fail

    Example:
        result = retry_on_network_error(
            lambda: client.table("news_urls").select("*").execute(),
            max_retries=3,
        )
    """
    # Import here to avoid import errors if packages not installed
    retryable_errors = []
    
    try:
        import httpx
        retryable_errors.extend([
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
        ])
        # These may not exist in all versions
        if hasattr(httpx, "LocalProtocolError"):
            retryable_errors.append(httpx.LocalProtocolError)
        if hasattr(httpx, "RemoteProtocolError"):
            retryable_errors.append(httpx.RemoteProtocolError)
    except ImportError:
        pass

    try:
        from httpcore import LocalProtocolError, RemoteProtocolError
        retryable_errors.extend([LocalProtocolError, RemoteProtocolError])
    except ImportError:
        pass

    # Add standard connection errors
    retryable_errors.extend([
        ConnectionError,
        ConnectionResetError,
        ConnectionRefusedError,
        TimeoutError,
    ])

    retryable_tuple = tuple(retryable_errors)
    delay = initial_delay
    last_exception = None

    for attempt in range(max_retries):
        try:
            return func()
        except retryable_tuple as e:
            last_exception = e
            if attempt < max_retries - 1:
                logger.warning(
                    "Network error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1,
                    max_retries,
                    e,
                    delay,
                )
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                logger.error("Network error after %d attempts: %s", max_retries, e)
                raise
        except Exception:
            # Non-retryable error, raise immediately
            raise

    if last_exception:
        raise last_exception
    
    # Should never reach here, but satisfy type checker
    raise RuntimeError("Retry loop completed without result or exception")
