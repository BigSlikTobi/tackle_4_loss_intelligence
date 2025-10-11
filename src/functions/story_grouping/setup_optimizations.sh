#!/bin/bash
# Quick setup script for story grouping performance optimizations
# Run this after applying the database migration

echo "============================================"
echo "Story Grouping Performance Optimization"
echo "============================================"
echo ""

# Check if we're in the right directory
if [ ! -f "scripts/group_stories_cli.py" ]; then
    echo "❌ Error: Run this script from src/functions/story_grouping/"
    exit 1
fi

echo "✓ Correct directory"
echo ""

# Check for migration file
if [ ! -f "migrations/002_optimize_queries.sql" ]; then
    echo "❌ Error: Migration file not found"
    exit 1
fi

echo "✓ Migration file found"
echo ""

echo "============================================"
echo "STEP 1: Apply Database Migration"
echo "============================================"
echo ""
echo "Please apply the database migration manually:"
echo "  1. Open your Supabase Dashboard"
echo "  2. Go to SQL Editor"
echo "  3. Copy the content from:"
echo "     migrations/002_optimize_queries.sql"
echo "  4. Paste and execute in SQL Editor"
echo ""
read -p "Press Enter after you've applied the migration..."
echo ""

echo "============================================"
echo "STEP 2: Verify Indexes"
echo "============================================"
echo ""
echo "Run this SQL in Supabase to verify indexes:"
echo ""
echo "  SELECT indexname, tablename"
echo "  FROM pg_indexes"
echo "  WHERE tablename IN ('story_groups', 'story_embeddings')"
echo "  ORDER BY tablename, indexname;"
echo ""
echo "You should see these new indexes:"
echo "  - idx_story_groups_status_created_at"
echo "  - idx_story_embeddings_created_at"
echo "  - idx_story_embeddings_news_url_id"
echo "  - idx_story_embeddings_created_at_news_url_id"
echo "  - idx_story_embeddings_with_vectors"
echo ""
read -p "Press Enter after verifying indexes..."
echo ""

echo "============================================"
echo "STEP 3: Test the Optimized Pipeline"
echo "============================================"
echo ""
echo "Testing with 7-day lookback (smaller dataset)..."
python scripts/group_stories_cli.py --threshold 0.8 --days 7
TEST_RESULT=$?
echo ""

if [ $TEST_RESULT -eq 0 ]; then
    echo "✅ Test successful!"
    echo ""
    echo "You can now run with full 14-day lookback:"
    echo "  python scripts/group_stories_cli.py --threshold 0.8 --days 14"
else
    echo "⚠️  Test encountered issues. Check the logs above."
    echo ""
    echo "Troubleshooting:"
    echo "  1. Verify database indexes were created"
    echo "  2. Check Supabase connection and timeout limits"
    echo "  3. Try with fewer days: --days 3"
    echo "  4. See PERFORMANCE_OPTIMIZATIONS.md for details"
fi

echo ""
echo "============================================"
echo "Setup Complete"
echo "============================================"
echo ""
echo "Documentation:"
echo "  - OPTIMIZATION_SUMMARY.md  - Quick overview"
echo "  - PERFORMANCE_OPTIMIZATIONS.md - Detailed guide"
echo "  - migrations/002_optimize_queries.sql - SQL migration"
echo ""
