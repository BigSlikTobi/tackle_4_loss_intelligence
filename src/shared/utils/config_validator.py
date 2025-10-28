"""
Configuration validation utilities.

Provides utilities for validating required environment variables with clear error messages.
"""

import os
from typing import List, Optional, Dict, Any


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


def require_env(name: str, description: Optional[str] = None) -> str:
    """
    Require an environment variable to be set.
    
    Args:
        name: Environment variable name
        description: Optional description of what the variable is used for
        
    Returns:
        The value of the environment variable
        
    Raises:
        ConfigurationError: If the environment variable is not set or empty
    """
    value = os.getenv(name)
    
    if not value:
        desc_msg = f" ({description})" if description else ""
        raise ConfigurationError(
            f"Missing required environment variable: {name}{desc_msg}\n"
            f"Please set {name} in your .env file or environment."
        )
    
    return value


def get_env_or_default(name: str, default: str, description: Optional[str] = None) -> str:
    """
    Get an environment variable with a default value.
    
    Args:
        name: Environment variable name
        default: Default value if not set
        description: Optional description for documentation
        
    Returns:
        The value of the environment variable or the default
    """
    return os.getenv(name, default)


def validate_config(required: List[str], optional: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Validate required configuration variables and gather optional ones.
    
    Args:
        required: List of required environment variable names
        optional: Dict mapping optional variable names to default values
        
    Returns:
        Dict with all configuration values
        
    Raises:
        ConfigurationError: If any required variable is missing
    """
    config = {}
    errors = []
    
    # Check required variables
    for var_name in required:
        value = os.getenv(var_name)
        if not value:
            errors.append(var_name)
        else:
            config[var_name] = value
    
    if errors:
        raise ConfigurationError(
            f"Missing required environment variables: {', '.join(errors)}\n"
            f"Please set these variables in your .env file or environment.\n"
            f"See .env.example for configuration template."
        )
    
    # Add optional variables with defaults
    if optional:
        for var_name, default_value in optional.items():
            config[var_name] = os.getenv(var_name, default_value)
    
    return config


def validate_int_env(name: str, default: Optional[int] = None, min_value: Optional[int] = None, 
                     max_value: Optional[int] = None) -> int:
    """
    Validate an integer environment variable.
    
    Args:
        name: Environment variable name
        default: Default value if not set
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        
    Returns:
        The validated integer value
        
    Raises:
        ConfigurationError: If the value is invalid
    """
    value_str = os.getenv(name)
    
    if not value_str:
        if default is None:
            raise ConfigurationError(f"Missing required integer environment variable: {name}")
        return default
    
    try:
        value = int(value_str)
    except ValueError:
        raise ConfigurationError(
            f"Invalid integer value for {name}: '{value_str}'\n"
            f"Expected an integer value."
        )
    
    if min_value is not None and value < min_value:
        raise ConfigurationError(
            f"Value for {name} ({value}) is below minimum allowed value ({min_value})"
        )
    
    if max_value is not None and value > max_value:
        raise ConfigurationError(
            f"Value for {name} ({value}) exceeds maximum allowed value ({max_value})"
        )
    
    return value


def validate_bool_env(name: str, default: bool = False) -> bool:
    """
    Validate a boolean environment variable.
    
    Accepts: true, false, yes, no, 1, 0 (case-insensitive)
    
    Args:
        name: Environment variable name
        default: Default value if not set
        
    Returns:
        The validated boolean value
        
    Raises:
        ConfigurationError: If the value is invalid
    """
    value_str = os.getenv(name)
    
    if not value_str:
        return default
    
    value_lower = value_str.lower()
    
    if value_lower in ("true", "yes", "1"):
        return True
    elif value_lower in ("false", "no", "0"):
        return False
    else:
        raise ConfigurationError(
            f"Invalid boolean value for {name}: '{value_str}'\n"
            f"Expected one of: true, false, yes, no, 1, 0"
        )


def validate_choice_env(name: str, choices: List[str], default: Optional[str] = None, 
                       case_sensitive: bool = False) -> str:
    """
    Validate an environment variable against a list of allowed choices.
    
    Args:
        name: Environment variable name
        choices: List of allowed values
        default: Default value if not set
        case_sensitive: Whether the comparison is case-sensitive
        
    Returns:
        The validated value
        
    Raises:
        ConfigurationError: If the value is not in choices
    """
    value = os.getenv(name)
    
    if not value:
        if default is None:
            raise ConfigurationError(f"Missing required environment variable: {name}")
        return default
    
    # Normalize for comparison if not case-sensitive
    compare_value = value if case_sensitive else value.lower()
    compare_choices = choices if case_sensitive else [c.lower() for c in choices]
    
    if compare_value not in compare_choices:
        raise ConfigurationError(
            f"Invalid value for {name}: '{value}'\n"
            f"Allowed values: {', '.join(choices)}"
        )
    
    return value


def check_config_override(override: Optional[Any], env_name: str, 
                         required: bool = True) -> Optional[Any]:
    """
    Helper to check for configuration override or fall back to environment variable.
    
    Args:
        override: Override value (if provided programmatically)
        env_name: Environment variable name to check
        required: Whether the configuration is required
        
    Returns:
        The override value if provided, otherwise the env value
        
    Raises:
        ConfigurationError: If required and neither override nor env is set
    """
    if override is not None:
        return override
    
    value = os.getenv(env_name)
    
    if required and not value:
        raise ConfigurationError(
            f"Missing required configuration: {env_name}\n"
            f"Provide via environment variable or programmatic override."
        )
    
    return value
