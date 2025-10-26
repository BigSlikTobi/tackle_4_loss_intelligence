# Article Translation Module

This module scaffolds the German translation service that converts generated English team articles into localized content using GPT-5-mini. It fulfills Task 7 of the Daily Team Update Pipeline implementation plan while maintaining the repository's function-based isolation pattern.

## Responsibilities
- Accept fully generated English team articles
- Invoke GPT-5-mini with strict structure-preserving prompts
- Preserve team names, player names, franchise designations, and technical football terminology
- Emit translated outputs with the original schema for downstream storage and linking

## Project Layout
```
core/
  contracts/     # Data models for translation inputs/outputs
  llm/           # GPT-5-mini client abstractions
  processors/    # Term preservation and structural validation helpers
functions/       # Cloud Function adapters (stub)
scripts/         # CLI tooling for manual translation runs
requirements.txt # Module-specific dependencies
```

## Configuration
The module relies on environment variables defined in the root `.env`. Future commits will add validation utilities under `core` to ensure required configuration values are present.

## Next Steps
- Define request/response contracts for translated articles
- Implement GPT-5-mini client with flex-mode invocation helpers
- Add processors for preserving terminology and validating structure
- Provide a CLI entry point for manual translation workflows
