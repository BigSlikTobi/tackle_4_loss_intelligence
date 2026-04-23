"""Configuration management for news extraction."""

from .loader import load_feed_config, FeedConfig, SourceConfig

__all__ = ["load_feed_config", "FeedConfig", "SourceConfig"]
