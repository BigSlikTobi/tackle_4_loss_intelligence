"""
Configuration loader for news extraction feeds.

Loads and validates YAML configuration for RSS feeds, sitemaps, and other
news sources. Provides structured access to source definitions and defaults.
Enhanced with comprehensive validation and environment-specific configurations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import yaml
import logging

logger = logging.getLogger(__name__)

# Configuration validation constants
VALID_SOURCE_TYPES = {"rss", "sitemap", "html"}
MIN_MAX_ARTICLES = 1
MAX_MAX_ARTICLES = 1000
MIN_DAYS_BACK = 1
MAX_DAYS_BACK = 365
MIN_TIMEOUT_SECONDS = 5
MAX_TIMEOUT_SECONDS = 300


@dataclass
class SourceConfig:
    """Configuration for a single news source."""

    name: str
    type: str  # 'rss', 'sitemap', 'html'
    publisher: str
    enabled: bool = True
    nfl_only: bool = True
    url: Optional[str] = None
    url_template: Optional[str] = None
    max_articles: Optional[int] = None
    days_back: Optional[int] = None
    extract_content: bool = False
    notes: Optional[str] = None

    def __post_init__(self):
        """Validate source configuration with comprehensive checks."""
        self._validate_required_fields()
        self._validate_type()
        self._validate_urls()
        self._validate_limits()

    def _validate_required_fields(self):
        """Validate required fields are present."""
        if not self.name or not self.name.strip():
            raise ValueError("Source name cannot be empty")
        
        if not self.publisher or not self.publisher.strip():
            raise ValueError(f"Source '{self.name}' must have a publisher")
        
        if not self.url and not self.url_template:
            raise ValueError(f"Source '{self.name}' must have either 'url' or 'url_template'")

    def _validate_type(self):
        """Validate source type."""
        if self.type not in VALID_SOURCE_TYPES:
            raise ValueError(f"Source '{self.name}' has invalid type '{self.type}'. Valid types: {', '.join(VALID_SOURCE_TYPES)}")

    def _validate_urls(self):
        """Validate URL formats."""
        urls_to_check = []
        if self.url:
            urls_to_check.append(self.url)
        if self.url_template:
            # For template validation, substitute common placeholders
            test_url = self.url_template.replace("{YYYY}", "2024").replace("{MM}", "01")
            urls_to_check.append(test_url)
        
        for url in urls_to_check:
            if not self._is_valid_url(url):
                raise ValueError(f"Source '{self.name}' has invalid URL: {url}")

    def _validate_limits(self):
        """Validate numeric limits."""
        if self.max_articles is not None:
            if not isinstance(self.max_articles, int) or not (MIN_MAX_ARTICLES <= self.max_articles <= MAX_MAX_ARTICLES):
                raise ValueError(f"Source '{self.name}' max_articles must be between {MIN_MAX_ARTICLES} and {MAX_MAX_ARTICLES}")
        
        if self.days_back is not None:
            if not isinstance(self.days_back, int) or not (MIN_DAYS_BACK <= self.days_back <= MAX_DAYS_BACK):
                raise ValueError(f"Source '{self.name}' days_back must be between {MIN_DAYS_BACK} and {MAX_DAYS_BACK}")

    def _is_valid_url(self, url: str) -> bool:
        """Validate URL format."""
        try:
            result = urlparse(url)
            return all([result.scheme in ('http', 'https'), result.netloc])
        except Exception:
            return False

    def get_url(self, **kwargs) -> str:
        """
        Get the URL for this source, applying template substitutions if needed.

        Args:
            **kwargs: Template variables (e.g., YYYY, MM) for url_template

        Returns:
            Fully resolved URL string
        """
        if self.url:
            return self.url

        if self.url_template:
            url = self.url_template
            for key, value in kwargs.items():
                url = url.replace(f"{{{key}}}", str(value))
            return url

        raise ValueError(f"Source '{self.name}' has no URL configured")


@dataclass
class FeedConfig:
    """
    Complete feed configuration with comprehensive validation.
    
    Validates all configuration parameters and provides environment-aware defaults.
    """

    version: int
    defaults: Dict[str, Any]
    sources: List[SourceConfig] = field(default_factory=list)

    def __post_init__(self):
        """Validate complete configuration."""
        self._validate_version()
        self._validate_defaults()
        self._validate_sources()

    def _validate_version(self):
        """Validate configuration version."""
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError(f"Configuration version must be a positive integer, got: {self.version}")

    def _validate_defaults(self):
        """Validate default settings."""
        if not isinstance(self.defaults, dict):
            raise ValueError("Defaults must be a dictionary")
        
        # Validate timeout
        timeout = self.defaults.get("timeout_seconds")
        if timeout is not None:
            if not isinstance(timeout, int) or not (MIN_TIMEOUT_SECONDS <= timeout <= MAX_TIMEOUT_SECONDS):
                raise ValueError(f"timeout_seconds must be between {MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS}")
        
        # Validate max_parallel_fetches
        max_parallel = self.defaults.get("max_parallel_fetches")
        if max_parallel is not None:
            if not isinstance(max_parallel, int) or not (1 <= max_parallel <= 50):
                raise ValueError("max_parallel_fetches must be between 1 and 50")
        
        # Validate user_agent
        user_agent = self.defaults.get("user_agent")
        if user_agent is not None:
            if not isinstance(user_agent, str) or not user_agent.strip():
                raise ValueError("user_agent must be a non-empty string")

    def _validate_sources(self):
        """Validate source configurations."""
        if not self.sources:
            raise ValueError("Configuration must contain at least one source")
        
        # Check for duplicate source names
        source_names = [s.name for s in self.sources]
        duplicates = set([name for name in source_names if source_names.count(name) > 1])
        if duplicates:
            raise ValueError(f"Duplicate source names found: {', '.join(duplicates)}")
        
        # Validate at least one enabled source
        enabled_sources = [s for s in self.sources if s.enabled]
        if not enabled_sources:
            logger.warning("No sources are enabled in configuration")

    @property
    def user_agent(self) -> str:
        """Get configured user agent string."""
        return self.defaults.get("user_agent", "T4L-End2End/1.0")

    @property
    def timeout_seconds(self) -> int:
        """Get configured HTTP timeout in seconds."""
        return self.defaults.get("timeout_seconds", 30)

    @property
    def max_parallel_fetches(self) -> int:
        """Get max number of parallel fetch operations."""
        return self.defaults.get("max_parallel_fetches", 10)

    def get_enabled_sources(self, source_filter: Optional[str] = None) -> List[SourceConfig]:
        """
        Get list of enabled sources, optionally filtered by name.

        Args:
            source_filter: Optional string to filter source names (case-insensitive substring match)

        Returns:
            List of enabled SourceConfig objects
        """
        sources = [s for s in self.sources if s.enabled]

        if source_filter:
            filter_lower = source_filter.lower()
            sources = [s for s in sources if filter_lower in s.name.lower()]

        return sources

    def get_source_by_name(self, name: str) -> Optional[SourceConfig]:
        """Get a specific source by exact name match."""
        for source in self.sources:
            if source.name == name:
                return source
        return None


def load_feed_config(config_path: Optional[str] = None, environment: Optional[str] = None) -> FeedConfig:
    """
    Load and parse feed configuration from YAML file with environment support.

    Args:
        config_path: Path to feeds.yaml file. If None, uses default location
        environment: Environment name (dev, staging, prod) for environment-specific overrides

    Returns:
        Parsed and validated FeedConfig object

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If YAML is malformed
        ValueError: If configuration is invalid
    """
    # Determine config path
    if config_path is None:
        config_path = Path(__file__).parent / "feeds.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Feed configuration not found: {config_path}")

    # Detect environment if not specified
    if environment is None:
        environment = os.getenv("NEWS_EXTRACTION_ENV", "dev").lower()

    logger.info(f"Loading feed configuration from {config_path} (environment: {environment})")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in configuration file: {e}") from e
    except Exception as e:
        raise ValueError(f"Error reading configuration file: {e}") from e

    # Validate top-level structure
    if not isinstance(raw_config, dict):
        raise ValueError("Feed configuration must be a YAML dictionary")

    if "version" not in raw_config:
        raise ValueError("Configuration must specify a version")

    version = raw_config.get("version")
    if not isinstance(version, int) or version != 1:
        raise ValueError(f"Unsupported configuration version: {version}. Expected version 1.")

    # Load base configuration
    defaults = raw_config.get("defaults", {})
    sources_data = raw_config.get("sources", [])

    # Apply environment-specific overrides
    if environment and f"environments.{environment}" in raw_config:
        env_config = raw_config[f"environments.{environment}"]
        
        # Override defaults
        if "defaults" in env_config:
            defaults.update(env_config["defaults"])
            logger.debug(f"Applied {environment} environment defaults")
        
        # Override source settings
        if "source_overrides" in env_config:
            sources_data = _apply_source_overrides(sources_data, env_config["source_overrides"])
            logger.debug(f"Applied {environment} environment source overrides")

    # Apply environment variable overrides
    defaults = _apply_env_var_overrides(defaults)

    # Parse and validate sources
    sources = []
    invalid_sources = []
    
    for i, source_data in enumerate(sources_data):
        try:
            # Merge with defaults for missing values
            merged_data = _merge_source_with_defaults(source_data, defaults)
            source = SourceConfig(**merged_data)
            sources.append(source)
        except (TypeError, ValueError) as e:
            invalid_sources.append(f"Source {i+1}: {e}")
            continue

    if invalid_sources:
        logger.warning(f"Skipped {len(invalid_sources)} invalid sources: {'; '.join(invalid_sources)}")

    if not sources:
        raise ValueError("No valid sources found in configuration")

    # Create and validate final configuration
    try:
        config = FeedConfig(version=version, defaults=defaults, sources=sources)
    except ValueError as e:
        raise ValueError(f"Configuration validation failed: {e}") from e

    enabled_count = len(config.get_enabled_sources())
    logger.info(f"Configuration loaded successfully: {len(sources)} sources ({enabled_count} enabled)")

    return config


def _apply_source_overrides(sources_data: List[Dict], overrides: Dict[str, Dict]) -> List[Dict]:
    """Apply environment-specific source overrides."""
    for source_data in sources_data:
        source_name = source_data.get("name")
        if source_name in overrides:
            source_data.update(overrides[source_name])
    return sources_data


def _apply_env_var_overrides(defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment variable overrides to defaults."""
    env_mappings = {
        "NEWS_HTTP_TIMEOUT": ("timeout_seconds", int),
        "NEWS_MAX_PARALLEL": ("max_parallel_fetches", int),
        "NEWS_USER_AGENT": ("user_agent", str),
    }
    
    for env_var, (config_key, type_func) in env_mappings.items():
        value = os.getenv(env_var)
        if value:
            try:
                defaults[config_key] = type_func(value)
                logger.debug(f"Override from {env_var}: {config_key} = {defaults[config_key]}")
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid value for {env_var}: {value} ({e})")
    
    return defaults


def _merge_source_with_defaults(source_data: Dict, defaults: Dict) -> Dict:
    """Merge source configuration with defaults for missing values."""
    merged = source_data.copy()
    
    # Apply defaults for missing optional fields
    default_mappings = {
        "max_articles": defaults.get("max_articles"),
        "days_back": defaults.get("days_back"),
    }
    
    for key, default_value in default_mappings.items():
        if key not in merged and default_value is not None:
            merged[key] = default_value
    
    return merged
