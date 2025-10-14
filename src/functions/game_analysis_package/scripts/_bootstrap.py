"""
Bootstrap script for CLI environment setup.

This script ensures the Python path is configured correctly and the environment
is loaded before running CLI commands. It should be imported at the top of all
CLI scripts.
"""

import sys
from pathlib import Path
import os

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Try to load shared utilities if available
try:
    from src.shared.utils.env import load_env
    from src.shared.utils.logging import setup_logging
    
    # Load environment variables from central .env file
    load_env()
    
    # Setup logging
    setup_logging()
except ImportError:
    # Fallback if shared utilities don't exist yet
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
