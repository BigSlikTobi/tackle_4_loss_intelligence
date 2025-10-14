# Implementation Plan

-
  1. [x] Set up module structure and core interfaces
  - Create directory structure following function-based isolation pattern
  - Define core data contracts and interfaces for game packages, analysis
    envelopes, and pipeline components
  - Set up module configuration files (requirements.txt, .env.example,
    README.md)
  - _Requirements: 8.1, 8.2, 8.3_

-
  2. [x] Implement input validation and game package contracts
- [x] 2.1 Create game package input contracts
  - Write GamePackageInput, PlayData, and GameInfo dataclasses with validation
  - Implement validation logic for required fields (season, week, game_id,
    plays)
  - Add basic validation tests for core functionality
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2.2 Implement package validation service
  - Write PackageValidator class with comprehensive validation logic
  - Add descriptive error messages identifying specific game and request issues
  - Add basic tests for validation success and failure cases
  - _Requirements: 1.1, 1.2_

-
  3. [x] Implement player extraction and relevance scoring
- [x] 3.1 Create player extraction service
  - Write PlayerExtractor class to scan plays and collect unique player IDs
  - Implement extraction from all play action fields (rusher, receiver, passer,
    returner, tackler, etc.)
  - Handle both individual IDs and lists of IDs in play data
  - Add basic tests for player extraction functionality
  - _Requirements: 2.1_

- [x] 3.2 Implement relevance scoring algorithm
  - Write RelevanceScorer class with impact signal computation
  - Implement scoring for play frequency, production metrics (yards, TDs), and
    high-leverage events
  - Create balanced selection logic (top 5 per team, significant QBs, scorers)
  - Write unit tests for scoring algorithms and selection rules
  - _Requirements: 2.2, 2.3, 2.4_

-
  4. [x] Create data request bundling system
- [x] 4.1 Implement combined data request builder
  - Write DataRequestBuilder class to create single combined requests
  - Build requests for play-by-play, snap counts, team context, and
    position-appropriate NGS data
  - Implement payload size management with inline data and pointers
  - Write unit tests for request building logic
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 4.2 Integrate with existing data loading providers
  - Write DataFetcher class using existing provider registry
  - Implement fetching from pbp, snap_counts, pfr, and ngs providers
  - Add error handling for upstream source failures and rate limiting
  - Write integration tests with mock providers
  - _Requirements: 3.4, 8.3_

-
  5. [x] Implement data processing and normalization
- [x] 5.1 Create data normalization service
  - Write DataNormalizer class to clean and standardize data
  - Replace invalid JSON values (NaN) with standard nulls
  - Ensure consistent identifiers across all data sources
  - Add data provenance tracking (source, version, retrieval time)
  - Write unit tests for normalization edge cases
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 5.2 Implement data merging logic
  - Write data merging functionality to create coherent structure
  - Key data by game (season, week, game_id), teams (home/away), and players
    (unique ID)
  - Handle conflicts and missing data gracefully
  - Write unit tests for merging scenarios
  - _Requirements: 4.4_

-
  6. [ ] Create summary computation services
- [ ] 6.1 Implement team summary calculations
  - Write GameSummarizer class for team-level metrics
  - Calculate total plays, total yards, yards per play, and success indicators
  - Ensure accuracy and consistency with underlying play-by-play data
  - Write unit tests for team summary calculations
  - _Requirements: 5.1, 5.3_

- [ ] 6.2 Implement player summary calculations
  - Add player-level summary computation to GameSummarizer
  - Calculate plays involved, touches, yards, TDs, notable events, and relevance
    scores
  - Ensure summaries match the underlying data
  - Write unit tests for player summary calculations
  - _Requirements: 5.2, 5.3_

-
  7. [ ] Create analysis envelope builder
- [ ] 7.1 Implement LLM-friendly envelope structure
  - Write AnalysisEnvelopeBuilder class for compact envelope creation
  - Create game header, team summaries, and player map components
  - Implement key sequence extraction for notable game moments
  - Manage envelope size while maintaining analytical richness
  - Write unit tests for envelope structure and content
  - _Requirements: 6.1, 6.3_

- [ ] 7.2 Implement data pointer management
  - Add pointer/link creation for comprehensive datasets outside envelope
  - Link to detailed NGS tables and supplementary data
  - Ensure pointers are accessible and properly formatted
  - Write unit tests for pointer generation and linking
  - _Requirements: 6.2, 6.4_

-
  8. [ ] Create main pipeline orchestration
- [ ] 8.1 Implement GameAnalysisPipeline class
  - Write main pipeline class orchestrating all 9 steps
  - Integrate validation, extraction, scoring, bundling, fetching,
    normalization, summarization, and envelope creation
  - Add comprehensive error handling and logging throughout pipeline
  - Write integration tests for complete pipeline execution
  - _Requirements: 1.3, 2.4, 3.4, 4.4, 5.3, 6.4_

- [ ] 8.2 Implement correlation ID management
  - Write correlation ID generation and tracking utilities
  - Ensure IDs are propagated through entire pipeline
  - Add logging and tracing capabilities for n8n integration
  - Write unit tests for correlation ID handling
  - _Requirements: 7.2, 7.3_

-
  9. [x] Create CLI interface
- [x] 9.1 Implement command-line tool
  - Write analyze_game_cli.py script for local testing and development
  - Add support for JSON file input and pretty-printed output
  - Include dry-run and verbose logging options
  - Follow existing CLI patterns from other modules
  - Write CLI integration tests
  - _Requirements: 8.2_

- [x] 9.2 Add CLI configuration and help
  - Implement argument parsing with comprehensive help text
  - Add configuration validation and error reporting
  - Include usage examples and sample input files
  - Write documentation for CLI usage
  - _Requirements: 8.2_

-
  10. [ ] Implement HTTP API Cloud Function
- [ ] 10.1 Create Cloud Function entry point
  - Write functions/main.py with analysis_handler function
  - Implement CORS handling following existing patterns
  - Add comprehensive error handling (400, 422, 500, 405 responses)
  - Parse JSON requests and validate structure
  - Write unit tests for HTTP handler logic
  - _Requirements: 7.1, 7.2, 8.4_

- [ ] 10.2 Integrate pipeline with HTTP interface
  - Connect HTTP handler to GameAnalysisPipeline
  - Format responses with enriched packages and analysis envelopes
  - Add proper HTTP status codes and error messages
  - Implement request/response logging
  - Write integration tests for HTTP API
  - _Requirements: 7.1, 7.2_

-
  11. [x] Create deployment infrastructure
- [x] 11.1 Implement deployment scripts
  - Write deploy.sh script following existing module patterns
  - Create run_local.sh for local development testing
  - Set up Cloud Function configuration (name: game-analysis)
  - Add environment variable configuration for deployment
  - Write deployment documentation
  - _Requirements: 8.4_

- [x] 11.2 Create test requests and documentation
  - Create sample test request files in test_requests/ directory
  - Write comprehensive README.md with usage examples
  - Add API documentation with curl examples
  - Include troubleshooting and configuration guides
  - _Requirements: 8.4_

-
  12. [ ] Implement comprehensive testing
- [ ] 12.1 Create unit test suite
  - Write unit tests for all core components (extraction, scoring,
    normalization, etc.)
  - Add edge case testing for malformed data and error conditions
  - Implement mock providers for isolated testing
  - Ensure test coverage for all validation and error handling paths
  - _Requirements: 1.2, 2.4, 4.1, 5.3, 6.4_

- [ ] 12.2 Create integration and end-to-end tests
  - Write integration tests for complete pipeline with real game data
  - Test HTTP API with various request formats and error scenarios
  - Add performance testing for large games with many plays and players
  - Create manual testing procedures and validation checklists
  - _Requirements: 7.3, 8.4_
