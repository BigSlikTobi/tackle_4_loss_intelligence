"""
JSON-safe utilities for handling NaN and Infinity values.

This module provides utilities to ensure all data structures can be safely
serialized to JSON without encountering NaN, Infinity, or -Infinity values
that would cause errors in downstream JSON parsers.
"""

import json
import math
from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterable

import numbers

try:  # Optional NumPy support without hard dependency
    import numpy as _np  # type: ignore
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover - NumPy not installed
    _np = None
    _HAS_NUMPY = False


def clean_nan_values(obj: Any) -> Any:
    """
    Recursively clean NaN, Infinity, and -Infinity values from data structures.
    
    Replaces all float NaN/Infinity values with None (which becomes null in JSON).
    This ensures downstream JSON parsers never encounter these problematic values.
    
    Args:
        obj: Object to clean (dict, list, or primitive)
        
    Returns:
        Cleaned object with NaN/Infinity replaced by None
        
    Examples:
        >>> clean_nan_values({'a': float('nan'), 'b': 1.5})
        {'a': None, 'b': 1.5}
        
        >>> clean_nan_values([1, float('inf'), 3])
        [1, None, 3]
        
        >>> clean_nan_values({'nested': {'value': float('-inf')}})
        {'nested': {'value': None}}
    """
    # Dict / mapping types
    if isinstance(obj, dict):
        return {key: clean_nan_values(value) for key, value in obj.items()}

    # Sequence types (but not strings/bytes)
    if isinstance(obj, tuple):
        return tuple(clean_nan_values(item) for item in obj)
    if isinstance(obj, set):
        return {clean_nan_values(item) for item in obj}
    if isinstance(obj, list):
        return [clean_nan_values(item) for item in obj]

    if isinstance(obj, (str, bytes)):  # Leave scalar text as-is
        return obj

    # Booleans should remain untouched (they are numbers in Python)
    if isinstance(obj, bool):
        return obj

    # Handle Decimal explicitly
    if isinstance(obj, Decimal):
        if obj.is_nan() or not obj.is_finite():
            return None
        return obj

    # Handle Fractions explicitly
    if isinstance(obj, Fraction):
        # Fractions cannot represent NaN/Inf, so return as-is
        return obj

    # NumPy scalars (if NumPy is available)
    if _HAS_NUMPY and isinstance(obj, _np.generic):  # pragma: no branch - depends on environment
        if _np.isnan(obj) or _np.isinf(obj):
            return None
        return obj.item()

    # Generic numeric types
    if isinstance(obj, numbers.Number):
        try:
            numeric_value = float(obj)
        except (TypeError, ValueError, OverflowError):
            return obj

        if math.isnan(numeric_value) or math.isinf(numeric_value):
            return None
        return obj

    return obj


def json_dumps_safe(obj: Any, **kwargs) -> str:
    """
    Safely serialize object to JSON, ensuring no NaN/Infinity values.
    
    This function first cleans the object to remove NaN/Infinity values,
    then serializes with allow_nan=False to catch any edge cases.
    
    Args:
        obj: Object to serialize
        **kwargs: Additional arguments to pass to json.dumps
        
    Returns:
        JSON string
        
    Raises:
        ValueError: If NaN/Infinity values remain after cleaning
        
    Examples:
        >>> json_dumps_safe({'a': float('nan'), 'b': 1})
        '{"a": null, "b": 1}'
    """
    # Clean the object first
    cleaned = clean_nan_values(obj)
    
    # Force allow_nan=False to catch any edge cases
    kwargs['allow_nan'] = False
    
    # Serialize
    return json.dumps(cleaned, **kwargs)


class NaNSafeJSONEncoder(json.JSONEncoder):
    """
    Custom JSON encoder that converts NaN, Infinity, and -Infinity to null.
    
    Note: Prefer using json_dumps_safe() for most use cases, which pre-cleans
    the data. This encoder is provided for compatibility with code that needs
    a custom encoder class.
    
    Usage:
        >>> data = {'a': float('nan')}
        >>> json.dumps(clean_nan_values(data), cls=NaNSafeJSONEncoder)
        '{"a": null}'
    """
    
    def iterencode(self, o, _one_shot=False):
        """Encode object iteratively, cleaning NaN values first."""
        # Clean the object before encoding
        cleaned = clean_nan_values(o)
        return super().iterencode(cleaned, _one_shot)
    
    def default(self, obj):
        """Handle special float values as fallback."""
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
        return super().default(obj)


def is_json_safe(obj: Any) -> bool:
    """
    Check if an object can be safely serialized to JSON.
    
    Returns False if the object contains NaN or Infinity values.
    
    Args:
        obj: Object to check
        
    Returns:
        True if object is JSON-safe, False otherwise
        
    Examples:
        >>> is_json_safe({'a': 1, 'b': 2})
        True
        
        >>> is_json_safe({'a': float('nan')})
        False
        
        >>> is_json_safe([1, 2, float('inf')])
        False
    """
    try:
        json.dumps(obj, allow_nan=False)
        return True
    except (ValueError, TypeError):
        return False
