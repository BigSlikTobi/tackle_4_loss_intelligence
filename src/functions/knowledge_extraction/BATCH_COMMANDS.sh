#!/bin/bash
# Quick Reference: Batch Processing Commands for Knowledge Extraction

# =============================================================================
# GETTING STARTED
# =============================================================================

# 1. Check current progress
python scripts/extract_knowledge_cli.py --progress

# 2. Create batch job for all unextracted groups (RECOMMENDED)
python scripts/extract_knowledge_cli.py --batch

# 3. Create batch and wait for completion (auto-processes results)
python scripts/extract_knowledge_cli.py --batch --wait

# =============================================================================
# TESTING & DEVELOPMENT
# =============================================================================

# Test with small batch first (10 groups)
python scripts/extract_knowledge_cli.py --batch --limit 10 --wait

# Test with dry-run (no database writes)
python scripts/extract_knowledge_cli.py --batch --limit 10 --dry-run --wait

# Create batch for specific number of groups
python scripts/extract_knowledge_cli.py --batch --limit 100

# =============================================================================
# MONITORING BATCHES
# =============================================================================

# List all recent batches
python scripts/extract_knowledge_cli.py --batch-list

# Check status of specific batch
python scripts/extract_knowledge_cli.py --batch-status batch_abc123

# Check status with faster polling (every 30 seconds instead of 60)
python scripts/extract_knowledge_cli.py --batch-status batch_abc123 --poll-interval 30

# =============================================================================
# PROCESSING RESULTS
# =============================================================================

# Process completed batch results
python scripts/extract_knowledge_cli.py --batch-process batch_abc123

# Process with dry-run (preview without database writes)
python scripts/extract_knowledge_cli.py --batch-process batch_abc123 --dry-run

# =============================================================================
# ERROR HANDLING
# =============================================================================

# Retry failed groups (after main batch completes)
python scripts/extract_knowledge_cli.py --retry-failed --limit 10

# Create new batch for failed groups only
python scripts/extract_knowledge_cli.py --batch --retry-failed

# Cancel a running batch
python scripts/extract_knowledge_cli.py --batch-cancel batch_abc123

# =============================================================================
# PRODUCTION WORKFLOW (3,500 GROUPS)
# =============================================================================

# Step 1: Check what needs processing
python scripts/extract_knowledge_cli.py --progress

# Step 2: Create batch job
python scripts/extract_knowledge_cli.py --batch
# Output: batch_xyz789

# Step 3: Monitor progress (check every few hours)
python scripts/extract_knowledge_cli.py --batch-status batch_xyz789

# Step 4: Process results when completed
python scripts/extract_knowledge_cli.py --batch-process batch_xyz789

# Step 5: Verify results
python scripts/extract_knowledge_cli.py --progress

# Step 6: Handle any failures (if needed)
python scripts/extract_knowledge_cli.py --retry-failed

# =============================================================================
# COST COMPARISON
# =============================================================================

# 3,500 groups × 2 requests each = 7,000 API calls
#
# Synchronous:  7,000 × $0.005-0.01 = $35-70
# Batch:        7,000 × $0.0025-0.005 = $17-35  (50% savings!)
#
# Time:
# - Synchronous: 2-4 hours (active monitoring)
# - Batch: 12-24 hours (hands-off)

# =============================================================================
# ADVANCED OPTIONS
# =============================================================================

# Verbose logging
python scripts/extract_knowledge_cli.py --batch --verbose

# Custom log level
python scripts/extract_knowledge_cli.py --batch --log-level DEBUG

# Limit retry attempts for failed groups
python scripts/extract_knowledge_cli.py --batch --retry-failed --max-errors 5

# =============================================================================
# SYNCHRONOUS PROCESSING (for comparison)
# =============================================================================

# Process synchronously (real-time, more expensive)
python scripts/extract_knowledge_cli.py --limit 10

# Process with verbose logging
python scripts/extract_knowledge_cli.py --limit 10 --verbose

# Dry run (no database writes)
python scripts/extract_knowledge_cli.py --dry-run --limit 5
