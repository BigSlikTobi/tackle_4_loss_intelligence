
import sys
from datetime import datetime
from unittest.mock import MagicMock

# Mock modules to avoid import errors
sys.modules["requests"] = MagicMock()
sys.modules["openai"] = MagicMock()
sys.modules["rapidfuzz"] = MagicMock()
sys.modules["src.shared.db"] = MagicMock()
sys.modules["src.shared.db.connection"] = MagicMock()

# Add project root to path
sys.path.insert(0, "/Users/tobiaslatta/Projects/temp/Tackle_4_loss_intelligence")

from src.functions.content_summarization.scripts import content_pipeline_cli

def verify_prompt_formatting():
    print("Testing FACT_PROMPT formatting...")
    try:
        current_date = "2025-11-19"
        formatted = content_pipeline_cli.FACT_PROMPT.format(current_date=current_date)
        
        if current_date not in formatted:
            print("FAIL: Date not injected")
            return False
            
        if '{"facts":' not in formatted and '{\n  "facts":' not in formatted:
             print("FAIL: JSON structure malformed after formatting")
             print(formatted[-100:]) # Print end of prompt to debug
             return False
             
        print("PASS: Formatting successful")
        return True
    except KeyError as e:
        print(f"FAIL: KeyError during formatting: {e}")
        return False
    except Exception as e:
        print(f"FAIL: Unexpected error: {e}")
        return False

if __name__ == "__main__":
    if verify_prompt_formatting():
        sys.exit(0)
    else:
        sys.exit(1)
