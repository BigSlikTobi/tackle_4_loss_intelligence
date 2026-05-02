"""Async Gemini TTS batch service (submit / poll / worker).

Mirrors the architecture of ``url_content_extraction_service`` and
``article_knowledge_extraction``: callers submit one of three job types
(``create``, ``status``, ``process``), the worker delegates to the legacy
``gemini_tts_batch.core.service.TTSBatchService`` to do the actual work, and
the result is consumed on the next poll. Jobs live in the shared
``extraction_jobs`` Supabase table tagged ``service='gemini_tts_batch'``.
"""

SERVICE_NAME = "gemini_tts_batch"
JOB_ACTIONS = ("create", "status", "process")
