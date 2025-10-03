"""Shared logging configuration for all functions.

This module provides consistent logging setup across data_loading,
news_extraction, and any future functional modules.
"""

from __future__ import annotations
import logging
import os
import sys
from typing import Optional


def setup_logging(
    level: Optional[str] = None,
    format_string: Optional[str] = None,
    include_timestamp: bool = True
) -> None:
    """Configure root logger with console handler.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               If None, reads from LOG_LEVEL env var or defaults to INFO.
        format_string: Custom format string. If None, uses default format.
        include_timestamp: Whether to include timestamp in log messages.
    
    Example:
        >>> setup_logging(level="DEBUG")
        >>> logger = logging.getLogger(__name__)
        >>> logger.debug("Debug message")
    """
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    if format_string is None:
        if include_timestamp:
            format_string = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        else:
            format_string = "[%(levelname)s] %(name)s: %(message)s"
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=format_string,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True  # Override any existing configuration
    )
    
    # Set third-party loggers to WARNING to reduce noise
    for logger_name in ["urllib3", "requests", "supabase"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """Get a logger instance with optional custom level.
    
    Args:
        name: Logger name (typically __name__)
        level: Optional logging level override
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    if level:
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    return logger
