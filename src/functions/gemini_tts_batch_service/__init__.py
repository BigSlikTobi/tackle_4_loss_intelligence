"""Async Gemini TTS batch service (submit / poll / worker).

Mirrors the architecture of ``url_content_extraction_service`` and
``article_knowledge_extraction``: callers submit one of three job types
(``create``, ``status``, ``process``), the worker dispatches to a local
``TTSBatchService`` (in ``core/tts/``) to do the actual work, and the
result is consumed on the next poll. Jobs live in the shared
``extraction_jobs`` Supabase table tagged ``service='gemini_tts_batch'``.

Self-contained by design: this module does not import from any other
function module, so it can be deployed and deleted independently.
"""

SERVICE_NAME = "gemini_tts_batch"
JOB_ACTIONS = ("create", "status", "process")
