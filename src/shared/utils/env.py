"""Environment variable loading utilities.

This module provides consistent environment variable handling
across all functional modules.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def load_env(env_file: Optional[str] = None, override: bool = False) -> None:
    """Load environment variables from .env file.
    
    Args:
        env_file: Path to .env file. If None, searches for .env in current
                 directory and parent directories.
        override: Whether to override existing environment variables.
    
    Note:
        This function uses python-dotenv if available, otherwise
        falls back to manual parsing.
    """
    try:
        from dotenv import load_dotenv
        
        env_paths = []
        if env_file:
            env_path = Path(env_file)
            if env_path.exists():
                env_paths.append(env_path)
        else:
            current = Path.cwd()
            parents = list(current.parents)
            for parent in reversed(parents):
                candidate = parent / ".env"
                if candidate.exists():
                    env_paths.append(candidate)
            candidate = current / ".env"
            if candidate.exists():
                env_paths.append(candidate)

        if not env_paths:
            logger.debug("No .env file found, using system environment")
        else:
            seen = set()
            for path in env_paths:
                if path in seen:
                    continue
                load_dotenv(path, override=override)
                seen.add(path)
                logger.debug(f"Loaded environment from {path}")
            
    except ImportError:
        logger.warning("python-dotenv not installed, skipping .env loading")


def get_required_env(key: str) -> str:
    """Get required environment variable or raise error.
    
    Args:
        key: Environment variable name
    
    Returns:
        Environment variable value
    
    Raises:
        ValueError: If environment variable is not set
    """
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable {key} is not set")
    return value


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable with optional default.
    
    Args:
        key: Environment variable name
        default: Default value if not set
    
    Returns:
        Environment variable value or default
    """
    return os.getenv(key, default)
