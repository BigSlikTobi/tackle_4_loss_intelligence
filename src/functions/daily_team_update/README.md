# Daily Team Update Pipeline

The daily team update module orchestrates the end-to-end workflow for generating comprehensive NFL team articles. It coordinates URL discovery, content extraction, summarisation, long-form article generation, translation, image selection, and database persistence while respecting the platform's function-based isolation architecture.

## Features

- Fetches team metadata and recent news URLs from Supabase (via the `team-news-urls` Edge Function).
- Invokes the dedicated service modules for content extraction, summarisation, article generation, translation, and image selection.
- Persists English and translated articles plus image relationships in Supabase with idempotent upserts.
- Collects per-team metrics and error details suitable for monitoring dashboards.
- Supports parallel execution with configurable worker counts and graceful error handling.
- Provides a CLI for local or scheduled runs and a Cloud Function handler for serverless deployment.

## Directory Structure

```
src/functions/daily_team_update/
├── core/
│   ├── contracts/        # Pydantic models for configs and results
│   ├── db/               # Supabase data access helpers
│   ├── integration/      # Service and Supabase clients
│   ├── monitoring/       # Metrics and error aggregation
│   └── orchestration/    # Pipeline, processor, configuration loader
├── functions/            # Cloud Function handler and deploy script
├── scripts/              # CLI tools and scheduler helper
├── requirements.txt      # Module dependencies
└── README.md             # This file
```

## Prerequisites

- Python 3.11+
- Supabase project with `teams`, `team_article`, `article_images`, and `team_article_image` tables plus `team-news-urls` Edge Function.
- Deployed service endpoints for:
  - URL content extraction
  - Article summarisation
  - Team article generation
  - Article translation
  - Image selection (reuses the existing `image_selection` module)
- `.env` configured using `.env.example` as a template.

## Setup

```bash
cd src/functions/daily_team_update
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example ../../../../.env  # if not already present at repo root
```

The module reads all configuration from the root `.env` file via `src.shared.utils.env.load_env`.

## Running the Pipeline Locally

Use the CLI to trigger a run for specific teams or the entire league:

```bash
python -m src.functions.daily_team_update.scripts.run_pipeline_cli --team BUF --team KC --dry-run --verbose
```

Key CLI options:

- `--team` / `-t` – filter processing to specific team abbreviations (repeatable)
- `--parallel` – enable parallel processing using worker threads
- `--max-workers` – cap the number of workers when running in parallel
- `--no-continue-on-error` – fail fast instead of continuing after errors
- `--dry-run` – skip Supabase writes while exercising service calls
- `--image-count` – override the number of images requested per team
- `--output json` – emit a JSON payload instead of log-based summary

Example JSON output contains aggregated metrics, per-team results, and error details.

## Cloud Function Deployment

The `functions/main.py` handler mirrors the CLI logic for serverless execution. Deploy using the provided script:

```bash
cd src/functions/daily_team_update/functions
./deploy.sh
```

Deployment notes:

- The script packages the entire repository (for shared utilities) and creates temporary `main.py` / `requirements.txt` files suitable for Cloud Functions Gen 2.
- Credentials (Supabase keys, downstream service keys) are expected through the `.env`-driven environment variables. The function does **not** load secrets from Secret Manager; supply them via runtime configuration or request payloads if preferred.
- The HTTP endpoint accepts payload overrides, for example:

```json
{
  "teams": ["BUF", "KC"],
  "parallel": true,
  "dry_run": true,
  "image_count": 1
}
```

## Scheduling Helper

Generate a Cloud Scheduler command that targets the deployed function:

```bash
python -m src.functions.daily_team_update.scripts.schedule_pipeline \
  --url "https://REGION-PROJECT.cloudfunctions.net/daily-team-update" \
  --schedule "0 11 * * *" \
  --time-zone "America/New_York"
```

The script outputs a fully formed `gcloud scheduler jobs create http` command you can run to activate the daily schedule.

## Error Handling & Metrics

- `MetricsCollector` aggregates URLs processed, summaries generated, articles written, translations, and images.
- `ErrorHandler` captures stage-specific errors with retryability hints; the pipeline response includes a top-level `errors` array for quick inspection.
- Each `TeamProcessingResult` records stage durations and any failures encountered while processing that team.

## Extensibility

- Override defaults using environment variables documented in `.env.example`.
- Custom headers for downstream services can be injected via `<SERVICE>_HEADER_<HEADERNAME>` environment variables, enabling bespoke authentication strategies without code changes.
- The orchestration layer intentionally depends only on HTTP interfaces of downstream services, simplifying future replacements or mock implementations for testing.

## Testing

Integration testing depends on available downstream services. For smoke testing without side effects, run the CLI with `--dry-run` to exercise service calls and supabase interactions (reads only) while skipping database writes and relationship creation.
