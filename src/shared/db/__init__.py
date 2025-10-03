"""Shared database utilities."""

from .connection import get_supabase_client, SupabaseConfig

__all__ = ["get_supabase_client", "SupabaseConfig"]
