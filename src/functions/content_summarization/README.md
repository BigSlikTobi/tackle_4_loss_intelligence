# Content Summarization – Fact-First Pipeline

## Overview
The content_summarization module now runs a multi-step, fact-first workflow for NFL news URLs. Each batch pulls pending IDs from the Supabase Edge Function `get-pending-news-urls`, retrieves article text from the Cloud Run content extractor, and uses Gemma 3n to derive atomic one-sentence facts. Facts are inserted into `news_facts`, embedded individually with `text-embedding-3-small`, averaged into a URL-level vector, and then fed back into Gemma 3n to create concise factual summaries. No raw article text or hashes are persisted; only structured outputs derived from the facts are stored.

The workflow is modular so that facts, embeddings, and summaries can be recomputed independently. All configuration is sourced from the project-wide `.env` via `src.shared.utils.env.load_env`, and Supabase access is handled by `src.shared.db.get_supabase_client`.

## Database Tables
- `news_facts`: Atomic statements produced by the fact extractor (one factual clause per row). Each record captures the LLM model and prompt version used.
- `facts_embeddings`: Vector embeddings for every fact using `text-embedding-3-small`; downstream services can query them directly.
- `context_summaries`: Stores the Gemma 3n factual summary text generated strictly from the stored facts.
- `story_embeddings`: Holds derived embeddings. Records with `embedding_type = 'fact_pooled'` contain the mean vector across the fact embeddings for a URL, while `embedding_type = 'summary'` contains the embedding of the final summary text.

## Running the Pipeline Locally
```bash
cd src/functions/content_summarization
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run fact extraction + embeddings
python scripts/content_pipeline_cli.py --stage facts --limit 20

# Generate summaries and summary embeddings
python scripts/content_pipeline_cli.py --stage summary --limit 20

# Execute both stages sequentially
python scripts/content_pipeline_cli.py --stage full --limit 20
```

## Required Environment Variables
All configuration lives in the root `.env` file and is loaded via `load_env()` before execution. The module uses standard environment variables shared across the platform.

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_KEY` | Supabase connection (service role key recommended). Edge function URL is automatically derived from SUPABASE_URL. |
| `OPENAI_API_KEY` | OpenAI API key for LLM calls (fact extraction, summarization) and embeddings (`text-embedding-3-small`). |
| `CONTENT_EXTRACTION_URL` | Optional: Cloud Run HTTP endpoint that returns raw article text for a URL. If not configured, content extraction stage will be skipped. |
| `BATCH_LIMIT` | Optional default batch size pulled from the Edge Function. |
| `LLM_TIMEOUT_SECONDS`, `EMBEDDING_TIMEOUT_SECONDS`, `CONTENT_TIMEOUT_SECONDS` | Optional request timeouts for each service. |
| `FACT_LLM_MODEL` | Optional: Override the default model for fact extraction (default: `gemma-3n`). |
| `SUMMARY_LLM_MODEL` | Optional: Override the default model for summary generation (default: `gemma-3n`). |
| `OPENAI_EMBEDDING_MODEL` | Optional: Override the default embedding model (default: `text-embedding-3-small`). |

## Architecture Notes
- All orchestration code for the new pipeline lives under `core/` and `scripts/` within this module; no cross-module imports are used.
- Shared behaviour (logging, env loading, Supabase connection) comes exclusively from `src/shared` utilities, keeping the module replaceable.
- The script paginates Supabase reads to avoid hitting default row limits, and timestamps (`content_extracted_at`, `facts_extracted_at`, `summary_created_at`) are set only after their respective stages succeed.
