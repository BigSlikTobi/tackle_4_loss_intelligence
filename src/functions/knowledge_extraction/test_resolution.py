#!/usr/bin/env python3
"""Test resolution of Micah Parsons."""

import os
import sys
import logging

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.knowledge_extraction.core.resolution.entity_resolver import EntityResolver

# Load environment
load_env()
setup_logging(level="DEBUG")

print("=" * 80)
print("TESTING PLAYER RESOLUTION: Micah Parsons")
print("=" * 80)

resolver = EntityResolver()

# Test resolution with the exact parameters from extraction
result = resolver.resolve_player(
    mention_text="Micah Parsons",
    position="LB",
    team_name="Dallas Cowboys"
)

print()
if result:
    print("✅ RESOLUTION SUCCESSFUL!")
    print(f"   Player ID: {result.entity_id}")
    print(f"   Matched Name: {result.matched_name}")
    print(f"   Confidence: {result.confidence}")
else:
    print("❌ RESOLUTION FAILED!")
    print("   Player not found in database or filtered out")

print()
print("=" * 80)
print("TESTING WITH TEAM ABBR INSTEAD:")
print("=" * 80)

result2 = resolver.resolve_player(
    mention_text="Micah Parsons",
    position="LB",
    team_abbr="DAL"
)

print()
if result2:
    print("✅ RESOLUTION SUCCESSFUL!")
    print(f"   Player ID: {result2.entity_id}")
    print(f"   Matched Name: {result2.matched_name}")
    print(f"   Confidence: {result2.confidence}")
else:
    print("❌ RESOLUTION FAILED!")
    print("   Player not found in database or filtered out")

print()
print("=" * 80)
print("TESTING WITHOUT DISAMBIGUATION:")
print("=" * 80)

result3 = resolver.resolve_player(
    mention_text="Micah Parsons"
)

print()
if result3:
    print("✅ RESOLUTION SUCCESSFUL!")
    print(f"   Player ID: {result3.entity_id}")
    print(f"   Matched Name: {result3.matched_name}")
    print(f"   Confidence: {result3.confidence}")
else:
    print("❌ RESOLUTION FAILED!")
    print("   Player not found in database")
