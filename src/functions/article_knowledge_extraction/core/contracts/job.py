"""Job state contracts for the ephemeral article extraction job store."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class JobError:
    code: str
    message: str
    retryable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


@dataclass
class ExtractedEntityOut:
    """Structure of a single extracted entity in the job result payload."""

    entity_type: str
    mention_text: str
    confidence: Optional[float]
    rank: Optional[int]
    entity_id: Optional[str] = None
    matched_name: Optional[str] = None
    position: Optional[str] = None
    team_abbr: Optional[str] = None
    team_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "entity_type": self.entity_type,
            "mention_text": self.mention_text,
            "confidence": self.confidence,
            "rank": self.rank,
        }
        if self.entity_id is not None:
            payload["entity_id"] = self.entity_id
        if self.matched_name is not None:
            payload["matched_name"] = self.matched_name
        if self.position is not None:
            payload["position"] = self.position
        if self.team_abbr is not None:
            payload["team_abbr"] = self.team_abbr
        if self.team_name is not None:
            payload["team_name"] = self.team_name
        return payload


@dataclass
class ExtractedTopicOut:
    topic: str
    confidence: Optional[float]
    rank: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {"topic": self.topic, "confidence": self.confidence, "rank": self.rank}


@dataclass
class JobResult:
    """Terminal payload returned to callers on /poll success."""

    article_id: Optional[str]
    topics: list
    entities: list
    unresolved_entities: list
    metrics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "article_id": self.article_id,
            "topics": [t.to_dict() if hasattr(t, "to_dict") else t for t in self.topics],
            "entities": [e.to_dict() if hasattr(e, "to_dict") else e for e in self.entities],
            "unresolved_entities": [
                e.to_dict() if hasattr(e, "to_dict") else e for e in self.unresolved_entities
            ],
            "metrics": self.metrics,
        }
