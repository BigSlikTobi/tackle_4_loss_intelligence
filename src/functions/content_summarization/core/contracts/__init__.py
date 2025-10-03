"""
Data contracts for content summarization.

Defines the structure for content summaries and the database schema
for the context_summaries table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ContentSummary:
    """
    Comprehensive summary of a news article's content.

    This is the final format stored in the context_summaries table.
    Designed to capture factual information from the article without
    hallucination or external context.
    """

    # Reference to news_url record
    news_url_id: str  # UUID from news_urls table

    # Core Summary Content
    summary: str  # Comprehensive summary of article content
    key_points: list[str] = field(default_factory=list)  # Bullet points of main findings

    # Extracted Entities (structured data)
    players_mentioned: list[str] = field(default_factory=list)  # Player names
    teams_mentioned: list[str] = field(default_factory=list)  # Team names
    injury_updates: Optional[str] = None  # Injury-related information
    game_references: list[str] = field(default_factory=list)  # Referenced games

    # Metadata
    article_type: Optional[str] = None  # news, analysis, preview, recap, injury_report
    sentiment: Optional[str] = None  # positive, negative, neutral
    content_quality: Optional[str] = None  # high, medium, low (based on content depth)

    # LLM Processing Info
    model_used: Optional[str] = None  # e.g., "gemini-2.5-flash"
    tokens_used: Optional[int] = None  # Total tokens consumed
    processing_time_seconds: Optional[float] = None  # Time to generate summary
    url_retrieval_status: Optional[str] = None  # URL_RETRIEVAL_STATUS_SUCCESS, etc.

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_formatted_text(self) -> str:
        """
        Create a formatted text representation matching the CLI display format.
        
        Format without emojis, suitable for database storage.
        Matches the exact structure shown in the terminal output.
        
        Returns:
            Formatted string with all summary information
        """
        sections = []
        
        # Metadata section (first, as shown in CLI)
        if self.article_type or self.sentiment or self.content_quality:
            sections.append("Metadata:")
            if self.article_type:
                sections.append(f"  * Article Type: {self.article_type}")
            if self.sentiment:
                sections.append(f"  * Sentiment: {self.sentiment}")
            if self.content_quality:
                sections.append(f"  * Content Quality: {self.content_quality}")
        
        # Entities section
        if self.players_mentioned or self.teams_mentioned:
            entity_lines = ["Entities Extracted:"]
            if self.players_mentioned:
                players_display = ", ".join(self.players_mentioned[:5])
                entity_lines.append(f"  * Players: {players_display}")
                if len(self.players_mentioned) > 5:
                    entity_lines.append(f"    ... and {len(self.players_mentioned) - 5} more")
            if self.teams_mentioned:
                teams_display = ", ".join(self.teams_mentioned)
                entity_lines.append(f"  * Teams: {teams_display}")
            sections.append("\n".join(entity_lines))
        
        # Key points section (up to 5 visible)
        if self.key_points:
            key_lines = ["Key Points:"]
            for point in self.key_points[:5]:
                key_lines.append(f"  * {point}")
            if len(self.key_points) > 5:
                key_lines.append(f"  ... and {len(self.key_points) - 5} more")
            sections.append("\n".join(key_lines))
        
        # Summary section
        if self.summary:
            import textwrap
            # Wrap text at 76 characters
            wrapped = textwrap.fill(
                self.summary, 
                width=76, 
                initial_indent="  ", 
                subsequent_indent="  "
            )
            sections.append(f"Summary:\n{wrapped}")
        
        # Injury updates section
        if self.injury_updates:
            sections.append(f"Injury Updates:\n  {self.injury_updates}")
        
        return "\n\n".join(sections)

    def to_dict(self) -> dict:
        """
        Convert to dictionary for database insertion.
        Maps to existing database schema fields.

        Returns:
            Dictionary ready for Supabase upsert.
        """
        # Determine if fallback was used based on url_retrieval_status
        fallback_used = False
        if self.url_retrieval_status and "FALLBACK" in self.url_retrieval_status:
            fallback_used = True
        
        return {
            "news_url_id": self.news_url_id,
            "summary_text": self.to_formatted_text(),  # Complete structured response
            "llm_model": self.model_used,
            "fallback_used": fallback_used,
            "generated_at": self.created_at.isoformat() if self.created_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ContentSummary:
        """
        Create ContentSummary from database record.

        Args:
            data: Dictionary from Supabase query

        Returns:
            ContentSummary instance
        """
        # Parse datetime strings if present
        created_at = None
        if data.get("created_at"):
            if isinstance(data["created_at"], str):
                from dateutil import parser
                created_at = parser.parse(data["created_at"])
            else:
                created_at = data["created_at"]

        updated_at = None
        if data.get("updated_at"):
            if isinstance(data["updated_at"], str):
                from dateutil import parser
                updated_at = parser.parse(data["updated_at"])
            else:
                updated_at = data["updated_at"]

        return cls(
            news_url_id=data["news_url_id"],
            summary=data["summary"],
            key_points=data.get("key_points", []),
            players_mentioned=data.get("players_mentioned", []),
            teams_mentioned=data.get("teams_mentioned", []),
            injury_updates=data.get("injury_updates"),
            game_references=data.get("game_references", []),
            article_type=data.get("article_type"),
            sentiment=data.get("sentiment"),
            content_quality=data.get("content_quality"),
            model_used=data.get("model_used"),
            tokens_used=data.get("tokens_used"),
            processing_time_seconds=data.get("processing_time_seconds"),
            url_retrieval_status=data.get("url_retrieval_status"),
            created_at=created_at,
            updated_at=updated_at,
        )


@dataclass
class NewsUrlRecord:
    """
    Represents a record from the news_urls table.

    Used for reading URLs that need summarization.
    """

    id: str  # UUID
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    publication_date: Optional[datetime] = None
    source_name: Optional[str] = None
    publisher: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> NewsUrlRecord:
        """
        Create NewsUrlRecord from database record.

        Args:
            data: Dictionary from Supabase query

        Returns:
            NewsUrlRecord instance
        """
        from urllib.parse import unquote
        
        publication_date = None
        if data.get("publication_date"):
            if isinstance(data["publication_date"], str):
                from dateutil import parser
                publication_date = parser.parse(data["publication_date"])
            else:
                publication_date = data["publication_date"]

        # Decode URL if it's URL-encoded (e.g., %3A -> :)
        url = data["url"]
        if "%" in url:
            url = unquote(url)

        return cls(
            id=data["id"],
            url=url,
            title=data.get("title"),
            description=data.get("description"),
            publication_date=publication_date,
            source_name=data.get("source_name"),
            publisher=data.get("publisher"),
        )
