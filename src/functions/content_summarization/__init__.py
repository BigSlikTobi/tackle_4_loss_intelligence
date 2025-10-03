"""
Content Summarization Function Module

This module handles NFL news content summarization using LLM URL context capabilities.
It reads URLs from the news_url table, generates comprehensive summaries using
Google Gemini's URL context API, and stores results in the context_summaries table.

Key Features:
- LLM-powered content understanding (Google Gemini)
- Fact-based summarization (anti-hallucination prompts)
- Batch processing with error handling
- Dry-run mode for testing
- Comprehensive monitoring and logging
"""

__version__ = "1.0.0"
