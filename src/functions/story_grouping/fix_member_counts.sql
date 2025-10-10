-- Fix member_count for all story_groups
-- This updates the member_count column to match the actual number of members
-- in the story_group_members table.

-- Step 1: View current discrepancies
SELECT 
    COUNT(*) as groups_with_zero_count,
    SUM(actual_member_count) as total_actual_members
FROM group_summary
WHERE member_count = 0 AND actual_member_count > 0;

-- Step 2: Update all groups with correct member counts
UPDATE story_groups sg
SET 
    member_count = COALESCE(member_counts.count, 0),
    updated_at = NOW()
FROM (
    SELECT 
        group_id,
        COUNT(*) as count
    FROM story_group_members
    GROUP BY group_id
) member_counts
WHERE sg.id = member_counts.group_id
  AND sg.member_count != member_counts.count;

-- Step 3: Verify the fix
SELECT 
    COUNT(*) as total_groups,
    SUM(CASE WHEN member_count = 0 THEN 1 ELSE 0 END) as groups_with_zero,
    SUM(CASE WHEN member_count != actual_member_count THEN 1 ELSE 0 END) as mismatched_counts
FROM group_summary;

-- Step 4: Show sample of corrected groups
SELECT 
    id,
    member_count,
    actual_member_count,
    status,
    updated_at
FROM group_summary
ORDER BY updated_at DESC
LIMIT 10;
