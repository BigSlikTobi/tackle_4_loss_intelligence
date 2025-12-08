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
        # Apply schema to the postgrest client component only,
        # preserving the full client (which includes .storage, .auth, etc.)
        # Note: The postgrest property uses lazy initialization, so we must:
        # 1. Access client.postgrest to trigger initialization of _postgrest
        # 2. Set client._postgrest to the scoped client (the property has no setter)
        try:
            # Trigger lazy initialization
            _ = client.postgrest
            # Apply schema and update the internal attribute
            scoped_postgrest = client.postgrest.schema(config.schema)
            client._postgrest = scoped_postgrest
            logger.debug(f"Applied schema '{config.schema}' to postgrest client")
        except (AttributeError, TypeError) as exc:  # pragma: no cover - defensive
            logger.warning(
                "Failed to apply Supabase schema '%s': %s. Continuing with default schema.",
                config.schema,
                exc
            )
    
    return client
