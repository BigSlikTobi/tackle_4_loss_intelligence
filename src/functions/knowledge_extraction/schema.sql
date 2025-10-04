-- Knowledge Extraction Database Schema
-- 
-- This schema defines tables for extracting and storing key topics and entities
-- from story groups. Enables cross-referencing of stories based on shared topics
-- and linking stories to specific NFL entities (players, teams, games).

-- =============================================================================
-- story_topics
-- =============================================================================
-- Stores key topics extracted from story groups as text.
-- Topics enable finding cross-references between unrelated story groups.
-- Examples: "QB performance", "Sunday Night Football", "Touchdowns", "Injuries"

CREATE TABLE IF NOT EXISTS story_topics (
    -- Unique identifier for the topic record
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign key to story_groups (from story_grouping module)
    story_group_id UUID NOT NULL REFERENCES story_groups(id) ON DELETE CASCADE,
    
    -- Topic text (normalized, lowercase for consistency)
    -- Examples: "qb performance", "injury update", "trade rumors"
    topic TEXT NOT NULL,
    
    -- Confidence score from LLM extraction (0.0 to 1.0)
    -- Higher scores indicate stronger relevance
    confidence REAL,
    
    -- Timestamp when topic was extracted
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Ensure same topic isn't duplicated for a group
    CONSTRAINT story_topics_unique UNIQUE (story_group_id, topic)
);

-- Index on story_group_id for efficient lookups
CREATE INDEX IF NOT EXISTS idx_story_topics_group_id 
ON story_topics(story_group_id);

-- Index on topic for finding groups with same topic
CREATE INDEX IF NOT EXISTS idx_story_topics_topic 
ON story_topics(topic);

-- GIN index for full-text search on topics
CREATE INDEX IF NOT EXISTS idx_story_topics_topic_gin 
ON story_topics USING gin(to_tsvector('english', topic));

-- Index on confidence for filtering high-quality topics
CREATE INDEX IF NOT EXISTS idx_story_topics_confidence 
ON story_topics(confidence DESC) WHERE confidence IS NOT NULL;

COMMENT ON TABLE story_topics IS 
'Key topics extracted from story groups for cross-referencing';

COMMENT ON COLUMN story_topics.topic IS 
'Normalized topic text (lowercase) like "qb performance" or "injury update"';

COMMENT ON COLUMN story_topics.confidence IS 
'LLM confidence score (0.0-1.0) indicating topic relevance';


-- =============================================================================
-- story_entities
-- =============================================================================
-- Links story groups to specific NFL entities (players, teams, games).
-- Uses foreign keys to reference existing entities in the data_loading tables.
-- Supports multiple entity types in a single table using polymorphic pattern.

CREATE TABLE IF NOT EXISTS story_entities (
    -- Unique identifier for the entity link record
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign key to story_groups (from story_grouping module)
    story_group_id UUID NOT NULL REFERENCES story_groups(id) ON DELETE CASCADE,
    
    -- Type of entity: 'player', 'team', 'game'
    entity_type TEXT NOT NULL CHECK (entity_type IN ('player', 'team', 'game')),
    
    -- Entity ID (polymorphic - references different tables based on entity_type)
    -- For 'player': references players.player_id
    -- For 'team': references teams.team_abbr
    -- For 'game': references games.game_id
    entity_id TEXT NOT NULL,
    
    -- Original mention text from the story (for debugging/display)
    -- Examples: "Patrick Mahomes", "Chiefs", "Mahomes", "KC"
    mention_text TEXT,
    
    -- Confidence score from entity resolution (0.0 to 1.0)
    -- Lower scores may indicate fuzzy matches or nicknames
    confidence REAL,
    
    -- Whether this is a primary entity (main subject) or secondary mention
    is_primary BOOLEAN DEFAULT FALSE,
    
    -- Timestamp when entity was extracted
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Ensure same entity isn't duplicated for a group
    CONSTRAINT story_entities_unique UNIQUE (story_group_id, entity_type, entity_id)
);

-- Index on story_group_id for efficient lookups
CREATE INDEX IF NOT EXISTS idx_story_entities_group_id 
ON story_entities(story_group_id);

-- Composite index on entity_type and entity_id for reverse lookups
-- (e.g., "find all stories mentioning Patrick Mahomes")
CREATE INDEX IF NOT EXISTS idx_story_entities_type_id 
ON story_entities(entity_type, entity_id);

-- Index on entity_id for quick lookups
CREATE INDEX IF NOT EXISTS idx_story_entities_entity_id 
ON story_entities(entity_id);

-- Index on is_primary for filtering primary entities
CREATE INDEX IF NOT EXISTS idx_story_entities_primary 
ON story_entities(story_group_id) WHERE is_primary = TRUE;

-- Index on confidence for filtering high-quality matches
CREATE INDEX IF NOT EXISTS idx_story_entities_confidence 
ON story_entities(confidence DESC) WHERE confidence IS NOT NULL;

-- Index on extracted_at for chronological queries
CREATE INDEX IF NOT EXISTS idx_story_entities_extracted_at 
ON story_entities(extracted_at DESC);

COMMENT ON TABLE story_entities IS 
'Links story groups to NFL entities (players, teams, games)';

COMMENT ON COLUMN story_entities.entity_type IS 
'Type of entity: player, team, or game';

COMMENT ON COLUMN story_entities.entity_id IS 
'Entity ID (player_id, team_abbr, or game_id based on type)';

COMMENT ON COLUMN story_entities.mention_text IS 
'Original text mentioning this entity (e.g., "Mahomes", "Chiefs")';

COMMENT ON COLUMN story_entities.confidence IS 
'Confidence score (0.0-1.0) from entity resolution';

COMMENT ON COLUMN story_entities.is_primary IS 
'TRUE if entity is the main subject of the story';


-- =============================================================================
-- Utility Views
-- =============================================================================

-- View for player entities with player details
CREATE OR REPLACE VIEW story_player_entities AS
SELECT 
    se.id,
    se.story_group_id,
    se.entity_id AS player_id,
    se.mention_text,
    se.confidence,
    se.is_primary,
    se.extracted_at,
    p.display_name,
    p.position,
    p.latest_team,
    p.status
FROM story_entities se
LEFT JOIN players p ON se.entity_id = p.player_id
WHERE se.entity_type = 'player';

COMMENT ON VIEW story_player_entities IS 
'Story entities joined with player details';

-- View for team entities with team details
CREATE OR REPLACE VIEW story_team_entities AS
SELECT 
    se.id,
    se.story_group_id,
    se.entity_id AS team_abbr,
    se.mention_text,
    se.confidence,
    se.is_primary,
    se.extracted_at,
    t.team_name,
    t.team_conference AS conference,
    t.team_division AS division
FROM story_entities se
LEFT JOIN teams t ON se.entity_id = t.team_abbr
WHERE se.entity_type = 'team';

COMMENT ON VIEW story_team_entities IS 
'Story entities joined with team details';

-- View for game entities with game details
CREATE OR REPLACE VIEW story_game_entities AS
SELECT 
    se.id,
    se.story_group_id,
    se.entity_id AS game_id,
    se.mention_text,
    se.confidence,
    se.is_primary,
    se.extracted_at,
    g.season,
    g.week,
    g.game_type,
    g.home_team,
    g.away_team,
    g.home_score,
    g.away_score,
    g.gameday
FROM story_entities se
LEFT JOIN games g ON se.entity_id = g.game_id
WHERE se.entity_type = 'game';

COMMENT ON VIEW story_game_entities IS 
'Story entities joined with game details';


-- =============================================================================
-- Helper Functions
-- =============================================================================

-- Function to find story groups sharing topics
CREATE OR REPLACE FUNCTION find_groups_by_topic(
    topic_text TEXT
) RETURNS TABLE (
    story_group_id UUID,
    topic TEXT,
    confidence REAL,
    match_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        st.story_group_id,
        st.topic,
        st.confidence,
        COUNT(*) OVER (PARTITION BY st.story_group_id) as match_count
    FROM story_topics st
    WHERE st.topic ILIKE '%' || topic_text || '%'
    ORDER BY st.confidence DESC NULLS LAST, match_count DESC;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION find_groups_by_topic IS 
'Find story groups containing a specific topic (case-insensitive)';

-- Function to find story groups mentioning an entity
CREATE OR REPLACE FUNCTION find_groups_by_entity(
    entity_type_param TEXT,
    entity_id_param TEXT
) RETURNS TABLE (
    story_group_id UUID,
    mention_text TEXT,
    confidence REAL,
    is_primary BOOLEAN,
    extracted_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        se.story_group_id,
        se.mention_text,
        se.confidence,
        se.is_primary,
        se.extracted_at
    FROM story_entities se
    WHERE se.entity_type = entity_type_param
      AND se.entity_id = entity_id_param
    ORDER BY se.is_primary DESC, se.confidence DESC NULLS LAST, se.extracted_at DESC;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION find_groups_by_entity IS 
'Find story groups mentioning a specific entity (player, team, or game)';


-- =============================================================================
-- Indexes for Performance
-- =============================================================================

-- Additional composite indexes for common query patterns

-- Find topics for a specific group
CREATE INDEX IF NOT EXISTS idx_story_topics_group_topic 
ON story_topics(story_group_id, topic);

-- Find entities for a specific group by type
CREATE INDEX IF NOT EXISTS idx_story_entities_group_type 
ON story_entities(story_group_id, entity_type);

-- Find primary entities by type
CREATE INDEX IF NOT EXISTS idx_story_entities_type_primary 
ON story_entities(entity_type, entity_id, is_primary) WHERE is_primary = TRUE;
