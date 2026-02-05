# Issue Template (Use for all new issues)

## Summary
- Add a production-grade semantic image relevance service (vision scoring) for the image selection pipeline, decoupled from Cloud Functions.

## Context
- Wrong images are worse than no image. The current Cloud Function path cannot run heavier vision models (e.g., CLIP/HF), so semantic relevance checks are limited. A dedicated service can provide reliable relevance scoring without impacting cold-start latency.

## Scope
- In scope:
  - Evaluate and prototype an external image relevance scorer (Cloud Run GPU or managed vision API).
  - Define a minimal contract: input (image URLs + query + optional required_terms), output (score + pass/fail + reason).
  - Integrate image_selection to call the scorer for top-N candidates and gate selections on a threshold.
  - Observability: log scores, thresholds, and rejection reasons.
- Out of scope:
  - Rewriting image search providers.
  - Adding new data sources for images.

## Triage Tag
- Priority: Medium

## Acceptance Criteria
- [ ] A documented service contract exists (request/response JSON) for semantic image relevance scoring.
- [ ] A working prototype runs in a production-compatible environment (e.g., Cloud Run with GPU or managed vision API).
- [ ] image_selection can optionally call the scorer for top-N candidates and enforce a configurable pass threshold.
- [ ] Latency and cost are measured and documented (expected per-image cost and typical end-to-end latency).
- [ ] Feature can be toggled via request payload (no required env secrets).

## Tasks (Optional)
- [ ] Evaluate OpenAI vision model scoring vs. CLIP in a Cloud Run service.
- [ ] Define thresholds and fallback strategy (return zero images on low confidence).
- [ ] Add basic load tests with representative article text and candidate images.

## SOTA Resolution
- Use a dedicated vision relevance service (Cloud Run GPU or managed vision API) that returns a relevance score and strict gating, called only for the top-ranked candidates.

## Notes/Links (Optional)
- Consider sharing the scorer across other media pipelines if it proves reliable.
