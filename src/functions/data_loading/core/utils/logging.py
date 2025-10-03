"""
Logging Configuration
---------------------

This small module centralizes how logging is set up across the
application.  
The :func:`setup_logging` function configures Python’s ``logging`` module
with a sensible format and a log level chosen by the user (for example,
``INFO`` or ``DEBUG``).  It also calls :func:`setup_library_logging` to
adjust the log levels of some chatty third‑party libraries so they only
emit warnings and errors.

The :func:`get_logger` helper simply returns a logger with the project’s
configuration already applied.  Throughout the codebase we use
``get_logger(__name__)`` to create per‑module loggers.
"""

import logging
import sys
from typing import Optional


def setup_logging(level: str = "INFO",
                  format_string: Optional[str] = None,
                  include_timestamp: bool = True) -> None:
    """Set up centralized logging configuration.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        format_string: Custom format string.  If omitted, a sensible default
            is used.
        include_timestamp: Whether to include a timestamp on each log line.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Default format string
    if format_string is None:
        if include_timestamp:
            format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        else:
            format_string = '%(name)s - %(levelname)s - %(message)s'

    # Configure basic logging to stdout
    logging.basicConfig(
        level=numeric_level,
        format=format_string,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Tune third‑party loggers
    setup_library_logging()


def setup_library_logging() -> None:
    """Configure logging levels for third‑party libraries.

    Without this, some libraries may emit a lot of informational logs by
    default, which can clutter the output of the CLI scripts.  We dial
    these down to ``WARNING`` or higher to keep output focused on our
    application.
    """
    # Reduce noise from HTTP clients and Supabase
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('supabase').setLevel(logging.WARNING)

    # The nflreadpy library can be verbose; set to WARNING
    logging.getLogger('nflreadpy').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with standardized configuration.

    Args:
        name: The logger name (typically use ``__name__`` in the caller).

    Returns:
        A ``logging.Logger`` instance configured with the project’s
        logging settings.
    """
    return logging.getLogger(name)
