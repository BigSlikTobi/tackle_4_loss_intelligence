-- Migration: Add versioning support to injuries, rosters, and depth_charts tables
-- Date: 2025-11-10
-- Description: Adds version and is_current columns to track historical changes
--              within the same time period (season/week) for each table.

-- ============================================================================
-- IMPORTANT NOTES
-- ============================================================================
-- 1. With versioning, each load creates a NEW set of records (INSERT)
--    instead of updating existing records (UPSERT).
-- 2. No unique constraints are needed on (season, week, ...) combinations
--    because multiple versions can exist for the same time period.
-- 3. The loaders use conflict_columns=None to perform plain INSERTs.
-- 4. Previous versions are marked with is_current=false automatically.
-- ============================================================================

-- ============================================================================
-- INJURIES TABLE VERSIONING
-- ============================================================================
-- Tracks multiple updates to injury reports within the same week
-- (e.g., Wednesday initial report vs. Friday update)

ALTER TABLE injuries 
ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS is_current BOOLEAN DEFAULT true;

-- Create index for efficient versioning queries
CREATE INDEX IF NOT EXISTS idx_injuries_version 
ON injuries(season, week, season_type, version DESC);

-- Create index for current version lookups
CREATE INDEX IF NOT EXISTS idx_injuries_current 
ON injuries(season, week, season_type, is_current) 
WHERE is_current = true;

-- Add comment for documentation
COMMENT ON COLUMN injuries.version IS 'Monotonically increasing version number per (season, week, season_type). Allows tracking multiple injury report updates within the same week.';
COMMENT ON COLUMN injuries.is_current IS 'Flag indicating if this is the current/active version for the given (season, week, season_type).';


-- ============================================================================
-- ROSTERS TABLE VERSIONING
-- ============================================================================
-- Tracks roster changes within the same week
-- (e.g., practice squad promotions, IR moves during the week)

-- Check if season/week columns exist, add as TEXT if not (to match potential existing schema)
-- If they exist, they will be used as-is
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='rosters' AND column_name='season') THEN
        ALTER TABLE rosters ADD COLUMN season TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='rosters' AND column_name='week') THEN
        ALTER TABLE rosters ADD COLUMN week TEXT;
    END IF;
END $$;

ALTER TABLE rosters 
ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS is_current BOOLEAN DEFAULT true;

-- Create index for efficient versioning queries
CREATE INDEX IF NOT EXISTS idx_rosters_version 
ON rosters(season, week, version DESC);

-- Create index for current version lookups
CREATE INDEX IF NOT EXISTS idx_rosters_current 
ON rosters(season, week, is_current) 
WHERE is_current = true;

-- Add comment for documentation
COMMENT ON COLUMN rosters.season IS 'Season year for roster snapshot';
COMMENT ON COLUMN rosters.week IS 'Week number for roster snapshot';
COMMENT ON COLUMN rosters.version IS 'Monotonically increasing version number per (season, week). Allows tracking roster changes within the same week.';
COMMENT ON COLUMN rosters.is_current IS 'Flag indicating if this is the current/active roster version for the given (season, week).';


-- ============================================================================
-- DEPTH_CHARTS TABLE VERSIONING
-- ============================================================================
-- Tracks depth chart changes within the same week
-- (e.g., injury-related position changes, coaching staff adjustments)

-- Check if season/week columns exist, add as TEXT if not (to match potential existing schema)
-- If they exist, they will be used as-is
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='depth_charts' AND column_name='season') THEN
        ALTER TABLE depth_charts ADD COLUMN season TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='depth_charts' AND column_name='week') THEN
        ALTER TABLE depth_charts ADD COLUMN week TEXT;
    END IF;
END $$;

ALTER TABLE depth_charts 
ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS is_current BOOLEAN DEFAULT true;

-- Create index for efficient versioning queries
CREATE INDEX IF NOT EXISTS idx_depth_charts_version 
ON depth_charts(season, week, version DESC);

-- Create index for current version lookups
CREATE INDEX IF NOT EXISTS idx_depth_charts_current 
ON depth_charts(season, week, is_current) 
WHERE is_current = true;

-- Add comment for documentation
COMMENT ON COLUMN depth_charts.season IS 'Season year for depth chart snapshot';
COMMENT ON COLUMN depth_charts.week IS 'Week number for depth chart snapshot';
COMMENT ON COLUMN depth_charts.version IS 'Monotonically increasing version number per (season, week). Allows tracking depth chart changes within the same week.';
COMMENT ON COLUMN depth_charts.is_current IS 'Flag indicating if this is the current/active depth chart version for the given (season, week).';


-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
-- Run these queries after migration to verify the changes

-- Check injuries versioning columns
SELECT 
    season,
    week,
    season_type,
    version,
    is_current,
    COUNT(*) as record_count
FROM injuries
GROUP BY season, week, season_type, version, is_current
ORDER BY season DESC, week DESC, version DESC
LIMIT 10;

-- Check rosters versioning columns  
SELECT 
    season,
    week,
    version,
    is_current,
    COUNT(*) as record_count
FROM rosters
WHERE season IS NOT NULL AND week IS NOT NULL
GROUP BY season, week, version, is_current
ORDER BY season DESC, week DESC, version DESC
LIMIT 10;

-- Check depth_charts versioning columns
SELECT 
    season,
    week,
    version,
    is_current,
    COUNT(*) as record_count
FROM depth_charts
WHERE season IS NOT NULL AND week IS NOT NULL
GROUP BY season, week, version, is_current
ORDER BY season DESC, week DESC, version DESC
LIMIT 10;


-- ============================================================================
-- USAGE EXAMPLES
-- ============================================================================

-- Get current injuries for a specific week
SELECT * FROM injuries
WHERE season = 2025 
  AND week = 10 
  AND season_type = 'REG'
  AND is_current = true;

-- Get history of injury report updates for a week
SELECT 
    version,
    COUNT(*) as player_count,
    MIN(last_update) as first_update,
    MAX(last_update) as last_update
FROM injuries
WHERE season = 2025 
  AND week = 10 
  AND season_type = 'REG'
GROUP BY version
ORDER BY version DESC;

-- Get current roster for a specific week
SELECT * FROM rosters
WHERE season = '2025' 
  AND week = '10' 
  AND is_current = true;

-- Get current depth chart for a specific week
SELECT * FROM depth_charts
WHERE season = '2025' 
  AND week = '10' 
  AND is_current = true;


-- ============================================================================
-- ROLLBACK (if needed)
-- ============================================================================
-- Uncomment and run these statements if you need to rollback the migration

-- ALTER TABLE injuries DROP COLUMN IF EXISTS version;
-- ALTER TABLE injuries DROP COLUMN IF EXISTS is_current;
-- DROP INDEX IF EXISTS idx_injuries_version;
-- DROP INDEX IF EXISTS idx_injuries_current;

-- ALTER TABLE rosters DROP COLUMN IF EXISTS version;
-- ALTER TABLE rosters DROP COLUMN IF EXISTS is_current;
-- ALTER TABLE rosters DROP COLUMN IF EXISTS season;
-- ALTER TABLE rosters DROP COLUMN IF EXISTS week;
-- DROP INDEX IF EXISTS idx_rosters_version;
-- DROP INDEX IF EXISTS idx_rosters_current;

-- ALTER TABLE depth_charts DROP COLUMN IF EXISTS version;
-- ALTER TABLE depth_charts DROP COLUMN IF EXISTS is_current;
-- ALTER TABLE depth_charts DROP COLUMN IF EXISTS season;
-- ALTER TABLE depth_charts DROP COLUMN IF EXISTS week;
-- DROP INDEX IF EXISTS idx_depth_charts_version;
-- DROP INDEX IF EXISTS idx_depth_charts_current;
