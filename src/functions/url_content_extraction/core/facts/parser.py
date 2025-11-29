"""Parse LLM responses for fact extraction."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def parse_fact_response(payload: Dict[str, Any]) -> List[str]:
    """Validate and normalize facts payload structure.
    
    Args:
        payload: Parsed JSON response from LLM
        
    Returns:
        List of fact strings, empty if invalid
    """
    facts_raw = payload.get("facts") if isinstance(payload, dict) else None
    if not isinstance(facts_raw, list):
        return []

    facts: List[str] = []

    for item in facts_raw:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned:
                facts.append(cleaned)

    return facts


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Extract JSON from LLM text response, handling code blocks and truncation.
    
    Args:
        text: Raw text response that may contain JSON
        
    Returns:
        Parsed JSON dict, or empty dict if parsing fails
    """
    if not text:
        return {}
    
    # Remove control characters that break JSON parsing
    # Keep only tab, newline, and carriage return (valid JSON whitespace)
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\t\n\r')
    
    # First try: Match code block (may be incomplete/truncated)
    json_match = re.search(r'```(?:json)?\s*(\{.*)', text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
        # Remove trailing ``` if present
        json_str = re.sub(r'\s*```\s*$', '', json_str)
        
        # Clean control characters from JSON string
        json_str = ''.join(char for char in json_str if ord(char) >= 32 or char in '\t\n\r')
        
        result = _try_parse_json(json_str)
        if result:
            return result
    
    # Second try: Look for JSON object without code blocks
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_str = text[start_idx:end_idx + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    # Final fallback: Try parsing the entire text
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return {}


def _try_parse_json(json_str: str) -> Dict[str, Any]:
    """Try to parse JSON, attempting to fix truncation issues.
    
    Args:
        json_str: JSON string that may be incomplete
        
    Returns:
        Parsed dict or empty dict
    """
    # If JSON is incomplete, try to complete it
    if json_str.count('{') > json_str.count('}'):
        missing_braces = json_str.count('{') - json_str.count('}')
        missing_brackets = json_str.count('[') - json_str.count(']')
        json_str = json_str.rstrip() + ']' * max(0, missing_brackets) + '}' * missing_braces
    
    try:
        return json.loads(json_str, strict=False)
    except json.JSONDecodeError as e:
        error_msg = str(e)
        char_match = re.search(r'\(char (\d+)\)', error_msg)
        
        if char_match:
            error_pos = int(char_match.group(1))
            # Truncate at the error position
            truncated = json_str[:error_pos]
            
            # Handle unterminated string
            if "unterminated string" in error_msg.lower() or truncated.count('"') % 2 != 0:
                last_quote = truncated.rfind('"')
                if last_quote != -1:
                    truncated = truncated[:last_quote]
                    truncated = truncated.rstrip().rstrip(',').rstrip()
            
            # Close any unclosed structures
            truncated = truncated.rstrip()
            if truncated.count('{') > truncated.count('}'):
                missing = truncated.count('{') - truncated.count('}')
                if truncated.count('[') > truncated.count(']'):
                    missing_brackets = truncated.count('[') - truncated.count(']')
                    truncated = truncated + ']' * missing_brackets
                truncated = truncated + '}' * missing
            
            try:
                return json.loads(truncated, strict=False)
            except json.JSONDecodeError:
                pass
        
        # Try to find the last complete fact
        last_complete = re.findall(r'"[^"]*"(?:,|\s*\])', json_str)
        if last_complete:
            last_pos = json_str.rfind(last_complete[-1])
            if last_pos != -1:
                truncated = json_str[:last_pos + len(last_complete[-1])]
                if not truncated.rstrip().endswith(']'):
                    truncated = truncated.rstrip().rstrip(',') + '\n  ]\n}'
                elif not truncated.rstrip().endswith('}'):
                    truncated = truncated.rstrip() + '\n}'
                try:
                    return json.loads(truncated, strict=False)
                except json.JSONDecodeError:
                    pass
    
    return {}
