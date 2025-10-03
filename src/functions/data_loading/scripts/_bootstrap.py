"""Common bootstrap helpers for CLI scripts."""

from __future__ import annotations

import sys
from pathlib import Path


def configure_path() -> None:
    """Ensure the project root is on ``sys.path`` for package imports.
    
    This adds the T4L_data_loaders root (4 levels up from this file) to sys.path,
    enabling imports like: from src.functions.data_loading.core...
    """
    # _bootstrap.py is in: src/functions/data_loading/scripts/
    # We need to go up 4 levels to reach project root
    project_root = Path(__file__).resolve().parents[4]
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

