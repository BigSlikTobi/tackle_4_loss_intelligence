-- Database triggers to automatically maintain story_groups.member_count
-- 
-- These triggers ensure that member_count is always synchronized with the 
-- actual number of members in story_group_members table.

-- Function to update group member count when members are added or removed
CREATE OR REPLACE FUNCTION update_group_member_count()
RETURNS TRIGGER AS $$
BEGIN
    -- For INSERT and UPDATE
    IF (TG_OP = 'INSERT') THEN
        -- Increment member_count for the group
        UPDATE story_groups
        SET 
            member_count = member_count + 1,
            updated_at = NOW()
        WHERE id = NEW.group_id;
        
        RETURN NEW;
    
    -- For DELETE
    ELSIF (TG_OP = 'DELETE') THEN
        -- Decrement member_count for the group
        UPDATE story_groups
        SET 
            member_count = GREATEST(member_count - 1, 0),  -- Ensure non-negative
            updated_at = NOW()
        WHERE id = OLD.group_id;
        
        RETURN OLD;
    
    -- For UPDATE (if group_id changes - should be rare)
    ELSIF (TG_OP = 'UPDATE') THEN
        -- If the group_id changed, update both old and new groups
        IF (OLD.group_id != NEW.group_id) THEN
            -- Decrement old group
            UPDATE story_groups
            SET 
                member_count = GREATEST(member_count - 1, 0),
                updated_at = NOW()
            WHERE id = OLD.group_id;
            
            -- Increment new group
            UPDATE story_groups
            SET 
                member_count = member_count + 1,
                updated_at = NOW()
            WHERE id = NEW.group_id;
        END IF;
        
        RETURN NEW;
    END IF;
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if it exists
DROP TRIGGER IF EXISTS trigger_update_group_member_count ON story_group_members;

-- Create trigger on story_group_members table
CREATE TRIGGER trigger_update_group_member_count
    AFTER INSERT OR UPDATE OR DELETE ON story_group_members
    FOR EACH ROW
    EXECUTE FUNCTION update_group_member_count();

-- Add comment for documentation
COMMENT ON FUNCTION update_group_member_count() IS 
'Automatically maintains story_groups.member_count when members are added/removed';

COMMENT ON TRIGGER trigger_update_group_member_count ON story_group_members IS
'Keeps story_groups.member_count synchronized with actual member count';

-- Test the trigger (optional - uncomment to test)
/*
-- Get a test group
SELECT id, member_count FROM story_groups WHERE status = 'active' LIMIT 1;

-- Insert a test member (will increment count)
INSERT INTO story_group_members (group_id, news_url_id, similarity_score)
VALUES ('YOUR_GROUP_ID', 'YOUR_NEWS_URL_ID', 0.95);

-- Check the count was updated
SELECT id, member_count FROM story_groups WHERE id = 'YOUR_GROUP_ID';

-- Delete the test member (will decrement count)
DELETE FROM story_group_members 
WHERE group_id = 'YOUR_GROUP_ID' AND news_url_id = 'YOUR_NEWS_URL_ID';

-- Check the count was updated
SELECT id, member_count FROM story_groups WHERE id = 'YOUR_GROUP_ID';
*/
