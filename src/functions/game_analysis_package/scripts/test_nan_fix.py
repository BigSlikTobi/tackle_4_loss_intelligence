#!/usr/bin/env python3
"""
Test script to verify NaN/Infinity values are properly converted to null.

This script tests the json_safe utilities to ensure all edge cases are handled.
"""

import math
import json
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parents[4]
sys.path.insert(0, str(project_root))

from src.functions.game_analysis_package.core.utils.json_safe import (
    clean_nan_values,
    json_dumps_safe,
    is_json_safe,
    NaNSafeJSONEncoder
)


def test_clean_nan_values():
    """Test the clean_nan_values function."""
    print("Testing clean_nan_values()...")
    
    # Test dict with NaN
    data = {"a": float('nan'), "b": 1.5, "c": float('inf'), "d": float('-inf')}
    result = clean_nan_values(data)
    assert result == {"a": None, "b": 1.5, "c": None, "d": None}, f"Dict test failed: {result}"
    print("  ✓ Dict with NaN/Infinity")
    
    # Test list with NaN
    data = [1, float('nan'), 3, float('inf')]
    result = clean_nan_values(data)
    assert result == [1, None, 3, None], f"List test failed: {result}"
    print("  ✓ List with NaN/Infinity")
    
    # Test nested structures
    data = {
        "outer": {
            "inner": [1, float('nan'), {"deep": float('inf')}]
        }
    }
    result = clean_nan_values(data)
    expected = {
        "outer": {
            "inner": [1, None, {"deep": None}]
        }
    }
    assert result == expected, f"Nested test failed: {result}"
    print("  ✓ Nested structures")
    
    # Test primitives
    assert clean_nan_values(float('nan')) is None
    assert clean_nan_values(float('inf')) is None
    assert clean_nan_values(42) == 42
    assert clean_nan_values("hello") == "hello"
    print("  ✓ Primitives")
    
    print("✅ clean_nan_values() tests passed\n")


def test_json_dumps_safe():
    """Test the json_dumps_safe function."""
    print("Testing json_dumps_safe()...")
    
    # Test dict with NaN
    data = {"value": float('nan'), "score": 42}
    result = json_dumps_safe(data)
    parsed = json.loads(result)
    assert parsed == {"value": None, "score": 42}, f"JSON dumps test failed: {parsed}"
    print("  ✓ Dict with NaN serializes to null")
    
    # Test list
    data = [1, float('inf'), 3]
    result = json_dumps_safe(data)
    parsed = json.loads(result)
    assert parsed == [1, None, 3], f"List test failed: {parsed}"
    print("  ✓ List with Infinity serializes to null")
    
    # Test pretty printing
    data = {"a": float('nan')}
    result = json_dumps_safe(data, indent=2)
    assert '"a": null' in result, f"Pretty print failed: {result}"
    print("  ✓ Pretty printing works")
    
    print("✅ json_dumps_safe() tests passed\n")


def test_is_json_safe():
    """Test the is_json_safe function."""
    print("Testing is_json_safe()...")
    
    # Safe data
    assert is_json_safe({"a": 1, "b": "hello"}) is True
    print("  ✓ Safe dict detected")
    
    # Unsafe data with NaN
    assert is_json_safe({"a": float('nan')}) is False
    print("  ✓ NaN detected")
    
    # Unsafe data with Infinity
    assert is_json_safe([1, float('inf')]) is False
    print("  ✓ Infinity detected")
    
    print("✅ is_json_safe() tests passed\n")


def test_nan_safe_encoder():
    """Test the NaNSafeJSONEncoder class."""
    print("Testing NaNSafeJSONEncoder...")
    
    data = {"value": float('nan'), "score": 42}
    result = json.dumps(data, cls=NaNSafeJSONEncoder)
    parsed = json.loads(result)
    assert parsed == {"value": None, "score": 42}, f"Encoder test failed: {parsed}"
    print("  ✓ Encoder converts NaN to null")
    
    print("✅ NaNSafeJSONEncoder tests passed\n")


def test_real_world_scenario():
    """Test a real-world scenario with complex nested data."""
    print("Testing real-world scenario...")
    
    # Simulate game analysis response with NaN values
    data = {
        "game_info": {
            "game_id": "2024_01_SF_KC",
            "season": 2024,
            "week": 1
        },
        "player_summaries": {
            "00-0036322": {
                "name": "Patrick Mahomes",
                "passing_yards": 250.0,
                "completion_pct": float('nan'),  # Missing data
                "qbr": 95.5,
                "avg_time_to_throw": float('inf')  # Data error
            }
        },
        "team_summaries": {
            "KC": {
                "total_yards": 400,
                "yards_per_play": 6.5,
                "turnover_margin": float('nan')  # No turnovers yet
            }
        }
    }
    
    # Clean and serialize
    result = json_dumps_safe(data, indent=2)
    
    # Parse back
    parsed = json.loads(result)
    
    # Verify NaN became null
    assert parsed["player_summaries"]["00-0036322"]["completion_pct"] is None
    assert parsed["player_summaries"]["00-0036322"]["avg_time_to_throw"] is None
    assert parsed["team_summaries"]["KC"]["turnover_margin"] is None
    
    # Verify other values preserved
    assert parsed["player_summaries"]["00-0036322"]["passing_yards"] == 250.0
    assert parsed["team_summaries"]["KC"]["total_yards"] == 400
    
    print("  ✓ Complex real-world data handled correctly")
    print("✅ Real-world scenario test passed\n")


def main():
    """Run all tests."""
    print("=" * 60)
    print("JSON-Safe Utility Tests")
    print("=" * 60 + "\n")
    
    try:
        test_clean_nan_values()
        test_json_dumps_safe()
        test_is_json_safe()
        test_nan_safe_encoder()
        test_real_world_scenario()
        
        print("=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        print("\nThe game-analysis-package API will now return null instead of NaN.")
        print("Downstream JSON parsers will no longer encounter errors.")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
