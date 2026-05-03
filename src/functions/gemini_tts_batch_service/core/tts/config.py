"""Request models for Gemini TTS batch processing."""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


class Credentials(BaseModel):
    gemini: Optional[str] = Field(None, min_length=1, description="Gemini API key")


class SupabaseStorageConfig(BaseModel):
    url: str = Field(..., min_length=1, description="Supabase project URL")
    key: str = Field(..., min_length=1, description="Supabase service or anon key")
    bucket: str = Field("audio", min_length=1, description="Storage bucket name")
    path_prefix: str = Field(
        "gemini-tts-batch",
        min_length=1,
        description="Storage prefix for uploaded batch audio",
    )


class PronunciationGuide(BaseModel):
    term: str = Field(..., min_length=1, description="Word or name to pronounce")
    guide: str = Field(..., min_length=1, description="Pronunciation guide")


class TTSDirection(BaseModel):
    audio_profile: Optional[str] = Field(None, description="Performance and voice profile")
    scene: Optional[str] = Field(None, description="Scene-setting context for delivery")
    audience: Optional[str] = Field(None, description="Intended listener context")
    director_notes: Optional[str] = Field(None, description="Performance notes")
    pace: Optional[str] = Field(None, description="Desired pacing")
    warmth: Optional[str] = Field(None, description="Desired warmth or energy")
    must_hit: list[str] = Field(
        default_factory=list,
        description="Phrases or concepts to emphasize",
    )
    pronunciations: list[PronunciationGuide] = Field(
        default_factory=list,
        description="Pronunciation overrides or guidance",
    )


class TTSScript(BaseModel):
    intro: Optional[str] = Field(None, description="Intro section of the script")
    body: Optional[str] = Field(None, description="Body section of the script")
    outro: Optional[str] = Field(None, description="Outro section of the script")

    @model_validator(mode="after")
    def validate_sections(self) -> "TTSScript":
        if not any([self.intro, self.body, self.outro]):
            raise ValueError("script must contain at least one of intro, body, or outro")
        return self


class BatchItem(BaseModel):
    id: str = Field(..., min_length=1, description="Stable item identifier")
    text: Optional[str] = Field(None, min_length=1, description="Plain text to convert to speech")
    tts_prompt: Optional[str] = Field(
        None,
        min_length=1,
        description="Pre-rendered TTS prompt. Prefer structured fields for new callers.",
    )
    title: Optional[str] = Field(None, description="Optional title for traceability")
    voice_name: Optional[str] = Field(None, description="Optional per-item voice override")
    direction: Optional[TTSDirection] = Field(
        None,
        description="Structured performance and pronunciation guidance",
    )
    script: Optional[TTSScript] = Field(
        None,
        description="Structured script sections to render into a single prompt",
    )

    @model_validator(mode="after")
    def validate_content(self) -> "BatchItem":
        if not any([self.text, self.tts_prompt, self.script]):
            raise ValueError("each item must include text, tts_prompt, or script")
        return self


class CreateBatchRequest(BaseModel):
    action: Literal["create"]
    model_name: str = Field(..., min_length=1, description="Gemini TTS model name")
    voice_name: str = Field("Charon", min_length=1, description="Default voice name")
    items: list[BatchItem] = Field(..., description="Batch items to synthesize")
    credentials: Optional[Credentials] = None
    supabase: Optional[SupabaseStorageConfig] = Field(
        None,
        description="Optional storage config for future processing",
    )

    @model_validator(mode="after")
    def validate_items(self) -> "CreateBatchRequest":
        if not self.items:
            raise ValueError("items must contain at least one item")

        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("items must use unique ids")
        return self


class StatusBatchRequest(BaseModel):
    action: Literal["status"]
    batch_id: str = Field(..., min_length=1, description="Gemini batch job name")
    credentials: Optional[Credentials] = None


class ProcessBatchRequest(BaseModel):
    action: Literal["process"]
    batch_id: str = Field(..., min_length=1, description="Gemini batch job name")
    credentials: Optional[Credentials] = None
    supabase: SupabaseStorageConfig


BatchActionRequest = Union[CreateBatchRequest, StatusBatchRequest, ProcessBatchRequest]
