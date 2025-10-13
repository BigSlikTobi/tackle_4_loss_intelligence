# NFL Injury Reports Module

Scrapes and loads NFL injury reports from nfl.com with historical tracking and automated daily updates.

---

## 🚀 Quick Start

```bash
# 1. Create database table (run in Supabase SQL Editor)
# Execute schema_injuries.sql

# 2. Test the scraper
cd src/functions/data_loading
python scripts/injuries_cli.py --season 2025 --week 6 --dry-run

# 3. Load injury data
python scripts/injuries_cli.py --season 2025 --week 6

# 4. Enable automation (daily at 6 PM ET)
# Workflow runs automatically via GitHub Actions
```

---

## 📋 Features

- ✅ **Historical Tracking**: Preserves injury status for each week
- ✅ **Automated Updates**: Daily GitHub Actions workflow at 6 PM ET
- ✅ **Automatic Week Detection**: Calculates current NFL week from date
- ✅ **Fuzzy Player Matching**: Resolves player names to database IDs
- ✅ **Two Extraction Methods**: JSON parsing with HTML fallback
- ✅ **Trend Analysis**: Query injury patterns and recovery timelines

---

## 🗄️ Database Schema

The `injuries` table uses **versioned records** with historical tracking:

```sql
CREATE TABLE injuries (
    season INTEGER NOT NULL,           -- Season year (2025)
    week INTEGER NOT NULL,             -- Week number (1-18)
    season_type TEXT NOT NULL,         -- 'PRE', 'REG', or 'POST'
    team_abbr TEXT NOT NULL,           -- Team abbreviation ('PHI', 'NYG')
    player_id TEXT NOT NULL,           -- GSIS player ID
    player_name TEXT NOT NULL,         -- Display name
    injury TEXT,                       -- Injury description ('Ankle', 'Knee')
    practice_status TEXT,              -- Practice participation status
    game_status TEXT,                  -- Game availability ('Out', 'Questionable')
    last_update TIMESTAMPTZ NOT NULL,  -- Report timestamp
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (season, week, season_type, team_abbr, player_id)
);
```

### Key Design Decisions

**Versioned Primary Key**: `(season, week, season_type, team_abbr, player_id)`
- Each week gets independent records
- Historical tracking of injury progression
- Recovered players naturally don't appear in new weeks
- No stale data accumulation

**Benefits:**
- Track when players got injured and when they recovered
- Identify players with recurring injuries
- Analyze injury trends over time
- Query specific weeks independently

### Setup

Run `schema_injuries.sql` in Supabase SQL Editor to create the table.

---

## 💻 Command Line Interface

### Basic Usage

```bash
cd src/functions/data_loading
python scripts/injuries_cli.py --season 2025 --week 6 --season-type reg
```

### Options

| Option | Required | Description | Example |
|--------|----------|-------------|---------|
| `--season` | Yes | Season year | `2025` |
| `--week` | Yes | Week number | `6` (1-18 for regular season) |
| `--season-type` | No | Season phase | `reg` (default), `pre`, `post` |
| `--dry-run` | No | Preview without writing | Flag only |
| `--log-level` | No | Logging verbosity | `DEBUG`, `INFO`, `WARNING` |

**Note:** No `--clear` flag needed - upsert handles updates automatically.

### Examples

```bash
# Load current week with automatic detection
WEEK=$(python scripts/get_current_week.py | cut -d' ' -f1)
python scripts/injuries_cli.py --season 2025 --week $WEEK

# Preview without writing to database
python scripts/injuries_cli.py --season 2025 --week 6 --dry-run

# Load with debug logging
python scripts/injuries_cli.py --season 2025 --week 6 --log-level DEBUG

# Load preseason injuries
python scripts/injuries_cli.py --season 2025 --week 2 --season-type pre

# Load postseason injuries
python scripts/injuries_cli.py --season 2025 --week 1 --season-type post
```

---

## 🤖 Automated Daily Updates

**GitHub Actions Workflow:** `.github/workflows/injuries-daily.yml`

- **Schedule:** Daily at 6:00 PM ET (10:00 PM UTC)
- **Automatic Week Detection:** Uses `get_current_week.py` to calculate current week
- **Manual Trigger:** Available via GitHub Actions UI with custom parameters

### Manual Workflow Execution

1. Go to GitHub Actions → "Load NFL Injuries (Daily)"
2. Click "Run workflow"
3. Optionally override:
   - Season year
   - Week number
   - Season type
4. View logs for status and diagnostics

---

## 🔍 Week Calculator

**File:** `scripts/get_current_week.py`

Automatically determines current NFL week and season type based on date.

```bash
# Plain text output
python scripts/get_current_week.py
# Output: 6 reg

# JSON output (for automation)
python scripts/get_current_week.py --json
# Output: {"week": 6, "season_type": "reg"}
```

**Season Configuration:**
- Preseason: 3 weeks (early August)
- Regular Season: 18 weeks (September - January)
- Postseason: 4 weeks (January - February)

Update `SEASON_2025_START` and `PRESEASON_START` constants for future seasons.

---

## 📊 Query Examples

### Current Week Injuries

```sql
SELECT team_abbr, player_name, injury, game_status
FROM injuries
WHERE season = 2025 
  AND week = 6 
  AND season_type = 'REG'
ORDER BY team_abbr, player_name;
```

### Players Who Recovered

```sql
-- Injured in week 5 but not in week 6
SELECT i5.player_name, i5.team_abbr, i5.injury
FROM injuries i5
LEFT JOIN injuries i6 
  ON i5.player_id = i6.player_id 
  AND i5.team_abbr = i6.team_abbr
  AND i6.season = 2025 
  AND i6.week = 6 
  AND i6.season_type = 'REG'
WHERE i5.season = 2025 
  AND i5.week = 5 
  AND i5.season_type = 'REG'
  AND i6.player_id IS NULL;
```

### Players with Recurring Injuries

```sql
SELECT player_id, player_name, COUNT(*) as weeks_injured
FROM injuries
WHERE season = 2025 
  AND season_type = 'REG'
  AND injury IS NOT NULL
GROUP BY player_id, player_name
HAVING COUNT(*) > 3
ORDER BY weeks_injured DESC;
```

### Historical Injury Timeline for a Player

```sql
SELECT season, week, season_type, team_abbr, injury, game_status
FROM injuries
WHERE player_id = 'SOME_PLAYER_ID'
ORDER BY season DESC, week DESC;
```

### Injury Counts by Team (Current Week)

```sql
SELECT team_abbr, COUNT(*) as injured_count
FROM injuries
WHERE season = 2025 
  AND week = 6 
  AND season_type = 'REG'
GROUP BY team_abbr
ORDER BY injured_count DESC;
```

---

## 🔧 Data Source

**NFL.com Injury Report Page:**
- URL Pattern: `https://www.nfl.com/injuries/league/{season}/{season_type}{week}`
- Example: `https://www.nfl.com/injuries/league/2025/REG6`

**Extraction Methods:**
1. **JSON Parsing** (preferred): Extracts structured data from `__NEXT_DATA__` script tags
2. **HTML Table Scraping** (fallback): Parses HTML tables when JSON unavailable

**Handled by:** `src/functions/data_loading/core/data/fetch.py`

---

## 🔎 Player Resolution

The scraper automatically resolves player names to database IDs using:

1. **Direct ID Match**: Uses player IDs when provided in scraped data
2. **Fuzzy Matching**: Matches player names against `players` table using:
   - Display name match
   - First + last name match
   - Team filtering for disambiguation
   - Levenshtein distance for similar names

**Unresolved Players:**
- New players not yet in `players` table
- Recent trades/signings
- Practice squad players
- Logged as warnings for manual review

**File:** `src/functions/data_loading/core/data/loaders/injury/injuries.py`

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `schema_injuries.sql` | Database table schema |
| `scripts/injuries_cli.py` | Main CLI interface |
| `scripts/get_current_week.py` | Automatic week calculator |
| `.github/workflows/injuries-daily.yml` | Daily automation workflow |
| `core/data/fetch.py` | Web scraping logic |
| `core/data/transformers/injury.py` | Data transformation & team resolution |
| `core/data/loaders/injury/injuries.py` | Database writer with player matching |

---

## 🐛 Troubleshooting

### Error: Table does not exist

```
APIError: {'message': 'JSON could not be generated', 'code': 404, ...}
```

**Solution:** Run `schema_injuries.sql` in Supabase SQL Editor to create the `injuries` table.

### Warning: Unable to resolve player

```
WARNING - Unable to resolve player 'Jonathan Mingo' for team DAL
```

**Cause:** Player not found in `players` table (new signing, trade, practice squad)

**Solution:** 
- Add player to `players` table manually or via players loader
- Re-run injury scraper after player is added

### No records extracted

**Check:**
1. Verify URL is accessible: `https://www.nfl.com/injuries/league/2025/REG6`
2. Run with `--log-level DEBUG` to see scraping details
3. Check if injury reports have been published for that week

### Week detection incorrect

**Cause:** Season start dates need updating

**Solution:** Update `SEASON_2025_START` and `PRESEASON_START` in `scripts/get_current_week.py`

---

## 🚀 Deployment Status

- ✅ **Scraping Logic**: Fixed and tested (333+ records extracted)
- ✅ **Team Resolution**: 32 team name mappings added
- ✅ **Database Schema**: Created with versioning support
- ✅ **GitHub Actions**: Configured for daily automation
- ✅ **Week Detection**: Automatic calculation implemented
- ✅ **Historical Tracking**: Versioned primary key implemented
- ⏳ **Database Table**: Requires manual creation in Supabase
- ⏳ **Player Resolution**: 16 unresolved players (expected for new additions)

---

## 📚 Architecture

Follows the **function-based isolation** pattern:

```
src/functions/data_loading/
├── core/
│   ├── data/
│   │   ├── fetch.py                      # Web scraping
│   │   ├── transformers/injury.py        # Data transformation
│   │   └── loaders/injury/injuries.py    # Database writer
│   └── ...
├── scripts/
│   ├── injuries_cli.py                   # CLI interface
│   └── get_current_week.py               # Week calculator
├── schema_injuries.sql                   # Database schema
└── INJURIES.md                           # This file
```

**Independence:** Can be deleted without affecting other modules.

**Dependencies:** Isolated in module's `requirements.txt`.

**Shared Utilities:** Only uses `src.shared.utils` for logging and database connection.

---

## 🔄 Migration from Old Schema

If you previously had an `injuries` table with `PRIMARY KEY (team_abbr, player_id)`:

### Backup Old Data (Optional)

```sql
CREATE TABLE injuries_backup AS SELECT * FROM injuries;
```

### Apply New Schema

```sql
DROP TABLE IF EXISTS injuries CASCADE;
-- Then run schema_injuries.sql
```

### Test New Structure

```bash
cd src/functions/data_loading
python scripts/injuries_cli.py --season 2025 --week 6
```

### Verify

```sql
SELECT season, week, season_type, COUNT(*) as count
FROM injuries
GROUP BY season, week, season_type
ORDER BY season DESC, week DESC;
```

---

## 📖 Additional Resources

- **Main Module README**: [data_loading/README.md](README.md)
- **Architecture Guide**: [docs/architecture/function_isolation.md](../../../docs/architecture/function_isolation.md)
- **AI Agent Guidelines**: [AGENTS.md](../../../AGENTS.md)

---

**Built with function-based isolation for independence and maintainability.** 🚀
