#!/usr/bin/env python3
"""Test extraction on a specific story."""

import os
import sys
import logging

# Add parent directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.knowledge_extraction.core.extraction.entity_extractor import EntityExtractor

# Load environment
load_env()
setup_logging(level="DEBUG")

# Read test story
with open("test_story.txt", "r") as f:
    story_text = f.read()

print("=" * 80)
print("STORY TEXT:")
print("=" * 80)
print(story_text)
print()

# Extract entities
print("=" * 80)
print("EXTRACTING ENTITIES...")
print("=" * 80)

extractor = EntityExtractor()
entities = extractor.extract(story_text, max_entities=20)

print()
print("=" * 80)
print(f"EXTRACTED {len(entities)} ENTITIES:")
print("=" * 80)

for i, entity in enumerate(entities, 1):
    print(f"\n{i}. {entity.entity_type.upper()}: {entity.mention_text}")
    print(f"   Rank: {entity.rank}")
    print(f"   Confidence: {entity.confidence}")
    print(f"   Is Primary: {entity.is_primary}")
    if entity.entity_type == "player":
        print(f"   Position: {entity.position}")
        print(f"   Team Abbr: {entity.team_abbr}")
        print(f"   Team Name: {entity.team_name}")
    print(f"   Context: {entity.context}")

print()
print("=" * 80)
print("ANALYSIS:")
print("=" * 80)

players = [e for e in entities if e.entity_type == "player"]
teams = [e for e in entities if e.entity_type == "team"]

print(f"Players extracted: {len(players)}")
print(f"Teams extracted: {len(teams)}")

if not players:
    print("\n⚠️  NO PLAYERS EXTRACTED!")
    print("This indicates the LLM is not finding player mentions in the text.")
else:
    print("\n✅ Players found:")
    for p in players:
        print(f"   - {p.mention_text} (pos={p.position}, team={p.team_name or p.team_abbr})")
