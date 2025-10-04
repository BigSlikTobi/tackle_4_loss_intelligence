"""
Bootstrap module to ensure correct Python path for script execution.

This allows scripts to be run directly from the scripts/ directory.
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
