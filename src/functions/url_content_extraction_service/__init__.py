"""Async URL content extraction service (submit / pull / worker).

Mirrors the architecture of ``article_knowledge_extraction``: callers submit
one or more URLs, the service extracts article content asynchronously via
Playwright/light extractors, and the result is consumed on the next poll.
Jobs are persisted in the shared ``extraction_jobs`` table tagged with
``service='url_content_extraction'``.
"""

SERVICE_NAME = "url_content_extraction"
