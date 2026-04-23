"""Async news extraction service (submit / poll / worker).

Wraps the legacy ``news_extraction.NewsExtractionPipeline`` in the same
async-job pattern used by ``article_knowledge_extraction`` and
``url_content_extraction_service``. Jobs are persisted in the shared
``extraction_jobs`` table tagged ``service='news_extraction'``.
"""

SERVICE_NAME = "news_extraction"
