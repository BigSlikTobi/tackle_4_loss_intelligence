"""Shared Supabase connection utilities.

This module provides generic Supabase client creation that can be used
by any functional module (data_loading, news_extraction, etc.).
"""

from __future__ import annotations
import os
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SupabaseConfig:
    """Configuration for Supabase connection.
    
    Attributes:
        url: Supabase project URL
        key: Supabase API key (anon or service role)
        schema: Database schema to use (default: public)
    """
    url: str
    key: str
    schema: str = "public"
    
    @classmethod
    def from_env(
        cls,
        url_var: str = "SUPABASE_URL",
        key_var: str = "SUPABASE_KEY",
        schema_var: str = "SUPABASE_SCHEMA"
    ) -> SupabaseConfig:
        """Create configuration from environment variables.
        
        Args:
            url_var: Environment variable name for URL
            key_var: Environment variable name for key
            schema_var: Environment variable name for schema
        
        Returns:
            SupabaseConfig instance
        
        Raises:
            ValueError: If required environment variables are not set
        """
        url = os.getenv(url_var)
        key = os.getenv(key_var)
        schema = os.getenv(schema_var, "public")
        
        if not url or not key:
            raise ValueError(
                f"Missing required environment variables: {url_var} and/or {key_var}. "
                f"Please set them in your .env file or environment."
            )
        
        return cls(url=url, key=key, schema=schema)


def get_supabase_client(config: Optional[SupabaseConfig] = None):
    """Create Supabase client.
    
    Args:
        config: Optional SupabaseConfig. If None, loads from environment.
    
    Returns:
        Supabase client instance
    
    Raises:
        ImportError: If supabase package is not installed
        ValueError: If required configuration is missing
    
    Example:
        >>> client = get_supabase_client()
        >>> response = client.table("players").select("*").execute()
        
        >>> # Or with custom config
        >>> config = SupabaseConfig(url="...", key="...")
        >>> client = get_supabase_client(config)
    """
    try:
        from supabase import create_client, Client
    except ImportError:
        raise ImportError(
            "supabase package is not installed. "
            "Install it with: pip install supabase"
        )
    
    if config is None:
        config = SupabaseConfig.from_env()
    
    logger.debug(f"Creating Supabase client for {config.url}")
    
    client = create_client(config.url, config.key)
    
    if config.schema and config.schema != "public":
        applied_schema = False
        for attr_name in ("postgrest", "postgrest_client", "rest", "_postgrest_client"):
            target = getattr(client, attr_name, None)
            schema_fn = getattr(target, "schema", None)
            if callable(schema_fn):
                try:
                    setattr(client, attr_name, schema_fn(config.schema))
                    applied_schema = True
                    break
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Failed to apply Supabase schema via %s: %s", attr_name, exc)
                    break

        if not applied_schema:
            schema_fn = getattr(client, "schema", None)
            if callable(schema_fn):
                try:
                    scoped_client = schema_fn(config.schema)
                    if scoped_client is not None:
                        client = scoped_client
                        applied_schema = True
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Failed to apply Supabase schema on client: %s", exc)

        if applied_schema:
            logger.debug(f"Using schema: {config.schema}")
        else:
            logger.warning(
                "Supabase client does not support schema override; continuing with default schema"
            )
    
    return client
