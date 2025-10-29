"""Prompt templates for content summarization workflows."""

from __future__ import annotations

from typing import Optional

URL_SUMMARIZATION_PROMPT_TEMPLATE = """Analyze the content from this URL: {url}

CRITICAL INSTRUCTIONS:
1. If you CAN access the URL content:
   - ONLY use facts and information explicitly stated in the article
   - DO NOT add external context, background information, or your own knowledge
   - DO NOT make assumptions or inferences beyond what's written
   - Quote or paraphrase only what appears in the source content

2. If you CANNOT access the URL content (e.g., paywall, JavaScript-required, or blocked):
   - Clearly state that the content was not accessible
   - Return null/empty values for all fields
   - DO NOT attempt to guess or infer article content
   - DO NOT use your training data knowledge about similar topics

Please provide:

1. COMPREHENSIVE SUMMARY (3-5 paragraphs):
   - Summarize the main content and key messages
   - Include important details, quotes, and context from the article
   - Maintain factual accuracy

2. KEY POINTS (bullet list):
   - 5-7 main takeaways from the article
   - Each point should be a concise factual statement

3. ENTITIES MENTIONED:
   - Players: List all NFL player names mentioned (format: "FirstName LastName")
   - Teams: List all NFL team names mentioned (use official names)
   - Games: List any specific games referenced (format: "Team1 vs Team2, Week X")

4. ARTICLE CLASSIFICATION:
   - Type: (news, analysis, preview, recap, injury_report, transaction, or other)
   - Sentiment: (positive, negative, neutral, mixed)
   - Quality: (high, medium, low) based on depth and factual content

5. INJURY UPDATES (if applicable):
   - Highlight injury-related information with player names and details

6. SOURCE ACCESSIBILITY:
   - Indicate whether the URL content was accessible or blocked
"""

ARTICLE_CONTENT_PROMPT_TEMPLATE = """Analyze the following article content.

URL: {url}
{title_line}

CRITICAL INSTRUCTIONS:
1. ONLY use facts and information from the article content below
2. DO NOT add external context or your own knowledge
3. Extract structured information accurately

ARTICLE CONTENT:
{content}

Please provide:

1. COMPREHENSIVE SUMMARY (3-5 paragraphs):
   - Summarize the main content and key messages
   - Include important details and context
   - Maintain factual accuracy

2. KEY POINTS (bullet list):
   - 5-7 main takeaways
   - Each point should be concise and factual

3. ENTITIES MENTIONED:
   - Players: List all NFL player names (format: "FirstName LastName")
   - Teams: List all NFL team names (use official names)
   - Games: List any specific games referenced

4. ARTICLE CLASSIFICATION:
   - Type: (news, analysis, preview, recap, injury_report, transaction, or other)
   - Sentiment: (positive, negative, neutral, mixed)
   - Quality: (high, medium, low) based on depth

5. INJURY UPDATES (if applicable):
   - Any injury-related information

Provide the response as structured JSON with fields:
- summary (string)
- key_points (array of strings)
- players_mentioned (array of strings)
- teams_mentioned (array of strings)
- game_references (array of strings)
- article_type (string or null)
- sentiment (string or null)
- content_quality (string or null)
- injury_updates (string or null)
"""


def build_url_prompt(url: str) -> str:
    """Create the summarization prompt for a given URL."""

    return URL_SUMMARIZATION_PROMPT_TEMPLATE.format(url=url)


def build_article_content_prompt(
    *,
    url: str,
    content: str,
    title: Optional[str] = None,
) -> str:
    """Construct the prompt used when raw article content has been fetched."""

    title_line = f"Title: {title}" if title else ""
    return ARTICLE_CONTENT_PROMPT_TEMPLATE.format(
        url=url,
        title_line=title_line,
        content=content,
    )
