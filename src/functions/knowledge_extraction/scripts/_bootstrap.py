"""
Bootstrap script to add project root to sys.path.
This allows scripts to import from src.functions.knowledge_extraction.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[4]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
