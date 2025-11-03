# Daily Team Pipeline Setup Guide

This guide explains how to configure the daily team update pipeline with the new
article validation stage. Follow the steps below before running the pipeline in
any environment.

## 1. Confirm Prerequisites

- Python 3.10 or later is available in your shell.
- You have access to the Supabase project that stores team articles.
- The `article_validation` Cloud Function (or compatible service) is deployed
  and reachable from your environment.

## 2. Update Environment Variables

All runtime configuration lives in the project root `.env`. Copy
[`.env.example`](./.env.example) if you have not already:

```bash
cp .env.example .env
```

Populate the following variables so the validation stage can execute:

| Variable | Description |
| --- | --- |
| `ARTICLE_VALIDATION_URL` | HTTPS endpoint for the article validation service. |
| `ARTICLE_VALIDATION_API_KEY` | Optional API key passed as `X-API-Key`; leave blank if your endpoint does not require it. |
| `ARTICLE_VALIDATION_TIMEOUT` | Request timeout in seconds (defaults to `180`). |

The validation service uses the same Gemini credentials as summarization. Make
sure the `.env` also contains the following entries:

- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
- Optional: `GEMINI_MODEL`, `GEMINI_ENABLE_WEB_SEARCH`, `GEMINI_TIMEOUT_SECONDS`

For article generation and translation you still need:

- `OPENAI_API_KEY`
- Optional: `OPENAI_TEAM_MODEL`, `OPENAI_TRANSLATION_MODEL`

After editing `.env`, restart any running processes or reload shell sessions so
the updated variables are visible.

## 3. Verify Supabase Schema

The pipeline now persists review feedback returned by the validator. Ensure the
`team_article` table has a `review_reasons` column that accepts an array of
text values. A minimal migration looks like:

```sql
alter table public.team_article
    add column if not exists review_reasons text[] default '{}';
```

Apply this change in the Supabase SQL editor or your migration tool before
running the pipeline so inserts succeed.

## 4. Configure Service Endpoints

The pipeline reads service URLs and headers from environment variables with the
following prefixes:

- `CONTENT_EXTRACTION_*`
- `SUMMARIZATION_*`
- `ARTICLE_GENERATION_*`
- `ARTICLE_VALIDATION_*` (new)
- `TRANSLATION_*`
- `IMAGE_SELECTION_*`

Set each `*_URL` to your deployed function endpoint. If a service requires
authentication, populate `*_API_KEY` or `*_AUTHORIZATION` accordingly. You can
leave a block blank to run an in-process implementation when available.

## 5. Run the Pipeline

1. Install dependencies (once per environment):
   ```bash
   pip install -r requirements.txt
   ```
2. Execute the daily team update entry point:
   ```bash
   python main.py daily-team-update
   ```
3. Monitor logs for validation messages such as `Article validation decision`.

If validation rejects an article, the pipeline automatically regenerates it
once using the rejection reasons. When validation returns review feedback, the
pipeline stores those reasons in `team_article.review_reasons` for editorial
follow-up.

## Troubleshooting

- **Validation endpoint returns 401**: Re-check `ARTICLE_VALIDATION_API_KEY` and
  any additional headers required by the service.
- **Supabase insert fails**: Confirm the `review_reasons` column exists and that
  your service role key is configured in `.env`.
- **Validation not invoked**: Ensure `ARTICLE_VALIDATION_URL` is set; the stage
  is skipped when the endpoint configuration is missing.

Once these steps are complete, the new validation stage will run automatically
as part of the daily team pipeline.
