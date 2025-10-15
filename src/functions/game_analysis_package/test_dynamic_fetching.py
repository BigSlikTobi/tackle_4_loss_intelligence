"""
Test script for dynamic play fetching enhancement.

Tests the new play fetching feature that allows empty plays arrays.
"""

import sys
from pathlib import Path

# Add project root to path (go up 3 levels: game_analysis_package -> functions -> src -> project_root)
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.functions.game_analysis_package.core.contracts.game_package import GamePackageInput
from src.functions.game_analysis_package.core.pipeline.game_analysis_pipeline import GameAnalysisPipeline, PipelineConfig
from src.shared.utils.logging import setup_logging

def test_dynamic_play_fetching():
    """Test automatic play fetching with empty plays array."""
    
    # Setup logging
    setup_logging(level="INFO")
    print("\n" + "="*70)
    print("Testing Dynamic Play Fetching Enhancement")
    print("="*70 + "\n")
    
    # Test 1: Empty plays array (should fetch automatically)
    print("TEST 1: Empty plays array → Should fetch automatically")
    print("-" * 70)
    
    try:
        # Create package with empty plays
        package = GamePackageInput(
            season=2023,  # Use 2023 data that exists in database
            week=1,
            game_id="2023_01_DET_KC",  # Chiefs vs Lions week 1
            plays=[],  # Empty! Should trigger automatic fetching
            schema_version="1.0.0",
            producer="test_script"
        )
        
        print(f"✓ Created package with {len(package.plays)} plays")
        print(f"  needs_play_fetching() = {package.needs_play_fetching()}")
        
        # Process with pipeline
        pipeline = GameAnalysisPipeline()
        config = PipelineConfig(
            fetch_data=False,  # Don't fetch NGS data for speed
            enable_envelope=True,
            strict_validation=False  # Allow warnings, only fail on errors
        )
        
        print(f"\n▶ Processing game {package.game_id}...")
        result = pipeline.process(package, config)
        
        print(f"\n✅ Result: {result.status}")
        print(f"   Correlation ID: {result.correlation_id}")
        print(f"   Plays analyzed: {len(package.plays)}")
        print(f"   Players extracted: {result.players_extracted}")
        print(f"   Players selected: {result.players_selected}")
        
        if result.warnings:
            print(f"\n⚠️  Warnings:")
            for warning in result.warnings:
                print(f"     - {warning}")
        
        if result.status == "success":
            print(f"\n🎉 TEST 1 PASSED: Successfully fetched and analyzed plays!")
        else:
            print(f"\n❌ TEST 1 FAILED: {result.errors}")
            return False
            
    except Exception as e:
        print(f"\n❌ TEST 1 FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "="*70)
    print("All tests passed! ✅")
    print("="*70 + "\n")
    return True

if __name__ == "__main__":
    success = test_dynamic_play_fetching()
    sys.exit(0 if success else 1)
