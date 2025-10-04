#!/usr/bin/env python3
"""
Bootstrap script to add the project root to sys.path.

This allows imports from src/ to work correctly when running scripts
from within the module directory.
"""

import sys
from pathlib import Path

# Add project root to path (4 levels up: scripts -> story_grouping -> functions -> src -> root)
project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))
