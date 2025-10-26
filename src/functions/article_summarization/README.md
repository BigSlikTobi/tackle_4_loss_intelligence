# Article Summarization Module

This module scaffolds the AI-driven summarization service that converts extracted article content into concise summaries using Google's Gemini Gemma-3n model. It is aligned with Task 3 of the Daily Team Update Pipeline roadmap.

## Responsibilities
- Accept normalized article content from the extraction service
- Communicate with Gemini Gemma-3n using deterministic parameters
- Remove boilerplate, advertisements, and unrelated fragments
- Deliver structured summaries suited for downstream article generation work

## Project Layout
```
core/
  contracts/     # Pydantic models for summarization inputs/outputs
  llm/           # Gemini API client wrappers and rate limiting
  processors/    # Output cleaning and formatting helpers
functions/       # Cloud Function adapters (stub)
scripts/         # CLI tooling for manual summarization runs
requirements.txt # Module-specific dependencies
```

## Configuration
The service relies on the shared project `.env` file. Any module-specific configuration will be defined through explicit loaders inside `core` at a later stage.

## Next Steps
- Define request/response data contracts for summaries
- Implement the Gemini client with retries and safety configuration
- Build post-processing helpers that remove noise and enforce structure
- Provide a functional CLI for manual summarization runs
