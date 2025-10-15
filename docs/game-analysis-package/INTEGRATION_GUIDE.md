# Game Analysis API - Integration Guide for Non-Technical Users

## What is the Game Analysis API?

The Game Analysis API is a service that takes raw NFL game data (play-by-play information) and transforms it into organized, easy-to-understand summaries and insights. Think of it as a smart assistant that reads through an entire game and creates a comprehensive report with all the key information you need.

**What it does**:
- Takes a list of plays from an NFL game (or fetches them automatically)
- Identifies the most important players
- Calculates performance statistics (yards, touchdowns, efficiency, etc.)
- Enriches player data with names, positions, and teams (using nflreadpy)
- Creates two types of outputs:
  1. **Analysis Envelope**: A short, focused summary perfect for AI analysis (2-5 KB)
  2. **Enriched Package**: Complete detailed data with everything you might need (50-100 KB)

**Production URL**: `https://game-analysis-hjm4dt4a5q-uc.a.run.app`  
**Current Version**: Revision 00021-duk (October 2025)

## ⚠️ Important: Complete Game Analysis

**Common Confusion**: Do I send one play at a time?

**Answer**: **NO!** You send **ALL plays from the complete game** in a **single request**, and you get back analysis for the **entire game**.

- ✅ **Correct**: Send 120-180 plays (entire game) → Get complete game statistics
- ❌ **Wrong**: Send 1 play → Get analysis for 1 play

Think of it like this: You give the API the complete game "recording" (all plays), and it gives you back a complete "game report" (all statistics for all teams and players).

### Visual Example

```
YOU SEND:
┌─────────────────────────────────────────────────────────┐
│ Game Package: 2025_06_DEN_NYJ                           │
├─────────────────────────────────────────────────────────┤
│ Play 1: DEN pass, 15 yards                              │
│ Play 2: DEN run, 7 yards                                │
│ Play 3: DEN pass, 22 yards, TOUCHDOWN                   │
│ Play 4: NYJ run, 3 yards                                │
│ Play 5: NYJ pass, 11 yards                              │
│ ... (150 more plays) ...                                │
│ Play 156: DEN field goal, GOOD                          │
└─────────────────────────────────────────────────────────┘
                          ↓
              ONE REQUEST TO API
                          ↓
YOU GET BACK:
┌─────────────────────────────────────────────────────────┐
│ ✅ Complete Game Analysis                                │
├─────────────────────────────────────────────────────────┤
│ DEN Team Stats: 62 plays, 382 yards, 3 TDs             │
│ NYJ Team Stats: 56 plays, 245 yards, 1 TD              │
│                                                          │
│ Bo Nix (QB): 25/35, 287 yards, 2 TDs                   │
│ Breece Hall (RB): 15 carries, 67 yards, 1 TD           │
│ ... (stats for all key players) ...                     │
│                                                          │
│ + Analysis Envelope (AI summary of entire game)         │
│ + Complete enriched data (all plays with full details)  │
└─────────────────────────────────────────────────────────┘
```

## How It Works (Simple Overview)

### Input → Processing → Output

**You Send (ONE REQUEST FOR THE ENTIRE GAME)**:
- A package containing basic game info (season, week, game ID)
- **A list of ALL plays from the complete game** (typically 120-180 plays for a full NFL game)

**Important**: You send **all the plays at once** in a single request, not play-by-play. The API analyzes the entire game and gives you back complete game statistics.

**The API Does**:
1. Checks that your data is valid and complete
2. Finds all the players who participated **in the entire game**
3. Identifies the most impactful players **across all plays**
4. Calculates team and player statistics **for the complete game**
5. Creates easy-to-read summaries **of the entire game**
6. Packages everything up in a structured format

**You Get Back (ONE RESPONSE WITH COMPLETE GAME ANALYSIS)**:
- **Complete game summaries** (how each team performed across the entire game)
- **Complete player statistics** (who did what throughout the game)
- A compact "analysis envelope" (AI-friendly summary of the entire game)
- Complete enriched data (all the details from all plays)
- Validation warnings (if anything was missing from your input)

## 🚀 Two Ways to Use the API

You can use the API in two ways depending on your needs:

### Option 1: Simple Mode (Automatic Play Fetching) ⭐ RECOMMENDED

**Perfect for**: Quick analysis, testing, production use when you don't have play data readily available

**How it works**: Leave the `plays` array **empty**, and the API automatically fetches all plays from the database.

**Benefits**:
- ✅ **90% smaller requests** (< 1 KB vs 50-100 KB)
- ✅ **No data preparation required** - just send game identifiers
- ✅ **Always uses current database data** - no stale data issues
- ✅ **Simple integration** - minimal request structure

**Request example**:
```json
{
  "game_package": {
    "game_id": "2023_01_DET_KC",
    "season": 2023,
    "week": 1,
    "plays": []  // ← Empty array = automatic fetch!
  }
}
```

**Response includes**:
```json
{
  "processing": {
    "plays_fetched_dynamically": true  // ← Confirms automatic fetch
  }
}
```

**Fetch time**: ~2 seconds to fetch and analyze a complete game (120-180 plays)

### Option 2: Advanced Mode (Provide Your Own Plays)

**Perfect for**: Custom play data, modified data, offline analysis, or when you have pre-fetched data

**How it works**: Provide all plays in the `plays` array.

**Use when**:
- ✅ You have custom or modified play data
- ✅ You're working offline without database access
- ✅ You need to analyze historical data not in the database
- ✅ You want to test specific play scenarios

**Request example**:
```json
{
  "game_package": {
    "game_id": "2023_01_DET_KC",
    "season": 2023,
    "week": 1,
    "plays": [
      {
        "play_id": "play_1",
        "posteam": "DET",
        "defteam": "KC",
        "desc": "Lions pass complete to Amon-Ra St. Brown for 15 yards",
        "yards_gained": 15,
        "down": 1,
        "ydstogo": 10
      },
      // ... 120-180 more plays ...
    ]
  }
}
```

**Response includes**:
```json
{
  "processing": {
    "plays_fetched_dynamically": false  // ← Using provided plays
  }
}
```

### Quick Comparison

| Feature | Simple Mode | Advanced Mode |
|---------|------------|---------------|
| Request size | **< 1 KB** 🎯 | 50-100 KB |
| Setup required | None | Must prepare play data |
| Data source | Database (always current) | Your data |
| Fetch time | ~2 seconds | 0 (already in request) |
| Use case | Production, testing | Custom data, offline |
| Recommended | ✅ Yes | For special cases |

### CLI Tool Support

Both modes are supported in the CLI tool:

```bash
# Simple mode (automatic fetch)
python analyze_game_cli.py --request sample_game.json --fetch-plays --pretty

# Advanced mode (uses plays from JSON file)
python analyze_game_cli.py --request sample_game.json --pretty
```

## What You Get: Understanding the Response

When you send a request, you get back a JSON response with several main sections:

### 1. Status Information
Tells you if the analysis worked successfully and provides a tracking ID:
```
Status: "success" (or "partial" if some data was missing)
Correlation ID: "2025_06_DEN_NYJ-20251014215551-c3864397"
```

### 2. Game Information
Basic facts about the game:
```
Game ID: "2025_06_DEN_NYJ"
Season: 2025
Week: 6
```

### 3. Validation Results
Tells you if there were any issues with your input data:
```
Passed: true
Warnings: ["3 plays missing quarter information"]
```

### 4. Processing Metrics
Shows what was analyzed:
```
Players Extracted: 4
Players Selected: 4
Data Fetched: false
```

### 5. Game Summaries
**This is the main content** - contains two parts:

#### Team Summaries (for each team)
Shows how each team performed overall:
- Total plays run
- Total yards gained
- Passing yards vs rushing yards
- Touchdowns scored
- Points scored
- Conversion rates (3rd down, 4th down)
- Turnovers

Example for Denver:
```
Total Plays: 62
Total Yards: 382
Passing Yards: 287
Rushing Yards: 95
Yards Per Play: 6.2
Touchdowns: 3
Points Scored: 21
```

#### Player Summaries (for key players)
Shows individual player performance:
- Basic info (name, position, team)
- Plays involved in
- Position-specific stats:
  - **Quarterbacks**: Pass attempts, completions, yards, TDs, passer rating
  - **Running backs**: Rush attempts, yards, TDs, yards per carry
  - **Receivers**: Receptions, yards, TDs, yards per catch
  - **Defensive players**: Tackles, sacks, interceptions

### 6. Analysis Envelope
A compact, AI-optimized summary that includes:

#### Game Header
```json
{
  "game_id": "2025_06_DEN_NYJ",
  "season": 2025,
  "week": 6,
  "home_team": "NYJ",
  "away_team": "DEN",
  "date": "2025-10-06",
  "location": "MetLife Stadium"
}
```

#### Team Summaries (One Line Each)
```
NYJ: "56 plays, 245 yds (4.4 avg), 1 TD, 2 TO, 35:12 TOP"
DEN: "62 plays, 382 yds (6.2 avg), 3 TD, 0 TO, 24:48 TOP"
```

#### Player Map (Quick Reference)
```
Bo Nix (QB, DEN): "25/35, 287 yds, 2 TD, 118.3 rtg"
Breece Hall (RB, NYJ): "15 carries, 67 yds, 1 TD"
```

#### Key Moments
Highlights the most important sequences:
```
- "DEN 87yd TD drive" (plays 45-47)
- "NYJ turnover" (play 58)
- "DEN game-winning FG" (play 76)
```

#### Data Links
Points to where you can find the complete detailed data:
```
Play-by-Play: "enriched_package.plays[156 plays]"
Player Data: "enriched_package.player_data[18 players]"
Team Context: "enriched_package.team_data"
```

### 7. Enriched Package
Contains the complete, detailed data:

#### Plays Array
Every single play from the game with all details:
- Play ID
- Quarter, down, distance
- Teams involved
- Players involved
- Yards gained
- Play type (pass, run, punt, field goal)
- Result (touchdown, first down, turnover)

#### Player Data
Detailed information for selected players:
- Basic profile (name, position, team, number)
- Advanced statistics (Next Gen Stats when available)
- Snap counts
- Performance metrics

## How to Use the API

### Step 1: Prepare Your Game Data

You need to create a JSON request with this structure:

```json
{
  "schema_version": "1.0.0",
  "producer": "your-application-name",
  "fetch_data": false,
  "enable_envelope": true,
  "game_package": {
    "season": 2025,
    "week": 6,
    "game_id": "2025_06_DEN_NYJ",
    "plays": [
      {
        "play_id": "1",
        "game_id": "2025_06_DEN_NYJ",
        "posteam": "DEN",
        "defteam": "NYJ",
        "play_type": "pass",
        "yards_gained": 10,
        "passer_player_id": "00-0039732",
        "receiver_player_id": "00-0038783"
      }
    ]
  }
}
```

**What each field means**:

- `schema_version`: Always use "1.0.0" (tells the API what format you're using)
- `producer`: Your application name (for tracking who sent the request)
- `fetch_data`: 
  - `false` = Use only the play data you provide
  - `true` = Fetch additional data from databases (requires more time)
- `enable_envelope`: 
  - `true` = Include the compact analysis envelope in the response
  - `false` = Only return the full enriched package
- `game_package`: Your game data
  - `season`: Year (e.g., 2025)
  - `week`: Week number (1-18 for regular season)
  - `game_id`: Unique identifier (format: YYYY_WW_AWAY_HOME)
  - `plays`: **Array of ALL play objects from the complete game** (120-180 plays typical)

**Important**: The `plays` array should contain **all plays from the entire game**, not just one play or a subset. The API analyzes the complete game in one request.

**Play Data Fields** (each play object):
- `play_id`: Unique identifier for this play
- `game_id`: Must match the game_id above
- `posteam`: Team with possession (e.g., "DEN")
- `defteam`: Defensive team (e.g., "NYJ")
- `play_type`: Type of play ("pass", "run", "punt", "field_goal", etc.)
- `yards_gained`: Yards gained on this play
- Player IDs for whoever was involved:
  - `passer_player_id`: Who threw the ball
  - `receiver_player_id`: Who caught it
  - `rusher_player_id`: Who ran with it
  - `tackler_player_id`: Who made the tackle
  - etc.

**Typical Request Size**:
- Regular game: ~50-100 KB (120-160 plays)
- High-scoring game: ~100-150 KB (160-180 plays)

### Step 2: Send Your Request

**Using curl (command line)**:
```bash
curl -X POST https://game-analysis-hjm4dt4a5q-uc.a.run.app \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": "1.0.0",
    "producer": "my-app",
    "fetch_data": false,
    "enable_envelope": true,
    "game_package": {
      "season": 2025,
      "week": 6,
      "game_id": "2025_06_DEN_NYJ",
      "plays": [...]
    }
  }'
```

**Using n8n (workflow automation)**:
1. Add an "HTTP Request" node
2. Set method to "POST"
3. Set URL to: `https://game-analysis-hjm4dt4a5q-uc.a.run.app`
4. Add header: `Content-Type: application/json`
5. Set body to your JSON request
6. Connect to next step in workflow

**Using Python**:
```python
import requests
import json

url = "https://game-analysis-hjm4dt4a5q-uc.a.run.app"
headers = {"Content-Type": "application/json"}
data = {
    "schema_version": "1.0.0",
    "producer": "my-python-app",
    "fetch_data": False,
    "enable_envelope": True,
    "game_package": {
        "season": 2025,
        "week": 6,
        "game_id": "2025_06_DEN_NYJ",
        "plays": [...]
    }
}

response = requests.post(url, headers=headers, json=data)
result = response.json()
print(json.dumps(result, indent=2))
```

### Step 3: Handle the Response

**Check if it worked**:
Look at the HTTP status code:
- **200**: Success! Your data is ready
- **400**: Bad request (check your JSON format)
- **422**: Validation failed (missing required fields)
- **500**: Server error (try again later)

**Access the data**:
```python
# Check status
if result["status"] == "success":
    # Get game summaries
    teams = result["game_summaries"]["team_summaries"]
    players = result["game_summaries"]["player_summaries"]
    
    # Get analysis envelope
    envelope = result["analysis_envelope"]
    game_info = envelope["game"]
    key_moments = envelope["key_moments"]
    
    # Get full data
    enriched = result["enriched_package"]
    all_plays = enriched["plays"]
    player_details = enriched["player_data"]
```

## Using the Data Links

One of the most powerful features is the **data links** in the analysis envelope. These tell you exactly where to find detailed data:

### Understanding Data Links

The envelope includes a `data_links` section that looks like this:

```json
{
  "play_by_play": {
    "type": "play_by_play",
    "location": "enriched_package.plays[156 plays]",
    "description": "Complete play-by-play data with all fields",
    "record_count": 156
  },
  "player_data": {
    "type": "player_enrichment",
    "location": "enriched_package.player_data[18 players]",
    "description": "Detailed player stats and NGS data",
    "player_count": 18
  }
}
```

**What this means**:
- `type`: What kind of data this is
- `location`: Where to find it in the response (path to the data)
- `description`: What's included in this dataset
- Counts: How many records are available

### How to Access Linked Data

**Example**: Getting all plays from the play-by-play link:

```python
# The link says: "enriched_package.plays[156 plays]"
# To access it:
all_plays = result["enriched_package"]["plays"]
print(f"Found {len(all_plays)} plays")

# Loop through plays
for play in all_plays:
    print(f"Play {play['play_id']}: {play['play_type']} for {play['yards_gained']} yards")
```

**Example**: Getting player details from the player_data link:

```python
# The link says: "enriched_package.player_data[18 players]"
# To access it:
player_data = result["enriched_package"]["player_data"]
print(f"Found {len(player_data)} players")

# Loop through players
for player in player_data:
    name = player.get("name", "Unknown")
    position = player.get("position", "??")
    team = player.get("team", "??")
    print(f"{name} ({position}, {team})")
```

### Navigating the Full Data Structure

The response has a **nested structure**. Think of it like folders on a computer:

```
response/
├── game_info/               → Basic game facts
├── game_summaries/          → Statistics and summaries
│   ├── team_summaries/      → Team performance
│   └── player_summaries/    → Player performance
├── analysis_envelope/       → Compact AI summary
│   ├── game/                → Game header
│   ├── teams/               → Team one-liners
│   ├── players/             → Player quick refs
│   ├── key_moments/         → Highlighted plays
│   └── data_links/          → Where to find full data
└── enriched_package/        → Complete detailed data
    ├── plays/               → All plays (follow play_by_play link)
    └── player_data/         → All players (follow player_data link)
```

**To access nested data**, use dots (.) or brackets:

```python
# Using dots
game_id = result.game_info.game_id

# Using brackets (safer if key might not exist)
game_id = result["game_info"]["game_id"]

# Get deep nested data
quarterback_stats = result["game_summaries"]["player_summaries"]["00-0039732"]
qb_name = quarterback_stats["player_name"]
qb_yards = quarterback_stats["passing_yards"]
```

### Combining Envelope + Full Data

**Use Case**: Start with the envelope, then drill down for details

```python
# 1. Get the compact envelope for quick overview
envelope = result["analysis_envelope"]
key_moments = envelope["key_moments"]

# 2. Find an interesting moment
touchdown_drive = key_moments[0]  # First key moment
play_ids = touchdown_drive["plays"]  # List of play IDs in this sequence

# 3. Get full details from enriched_package
all_plays = result["enriched_package"]["plays"]

# 4. Filter to just the plays in this drive
drive_plays = [p for p in all_plays if p["play_id"] in play_ids]

# 5. Show details
for play in drive_plays:
    print(f"{play['play_type']}: {play['yards_gained']} yards")
```

## Common Use Cases

### Use Case 1: Quick Game Overview for AI

**Goal**: Get a summary to feed to an AI for analysis

**What to use**: Just the `analysis_envelope`

```python
response = requests.post(api_url, json=request_data)
envelope = response.json()["analysis_envelope"]

# Feed to AI
ai_prompt = f"""
Analyze this NFL game:
Game: {envelope['game']['game_id']}
Teams: {envelope['game']['home_team']} vs {envelope['game']['away_team']}

Team Performance:
{envelope['teams'][0]['summary']}
{envelope['teams'][1]['summary']}

Key Moments:
{', '.join([m['label'] for m in envelope['key_moments']])}

What were the deciding factors in this game?
"""
```

### Use Case 2: Detailed Player Analysis

**Goal**: Analyze a specific player's performance

**What to use**: `game_summaries.player_summaries` + `enriched_package.player_data`

```python
# Get player ID from envelope
target_player = "00-0039732"  # Russell Wilson

# Get summary stats
player_summary = result["game_summaries"]["player_summaries"][target_player]
print(f"{player_summary['player_name']}: {player_summary['passing_yards']} yards")

# Get detailed data
player_details = result["enriched_package"]["player_data"]
player_full = [p for p in player_details if p["player_id"] == target_player][0]

# Analyze plays involving this player
all_plays = result["enriched_package"]["plays"]
player_plays = [p for p in all_plays if p.get("passer_player_id") == target_player]

print(f"Involved in {len(player_plays)} plays")
for play in player_plays:
    if play.get("touchdown"):
        print(f"  TD pass on play {play['play_id']}")
```

### Use Case 3: Drive-by-Drive Breakdown

**Goal**: Analyze each scoring drive

**What to use**: `analysis_envelope.key_moments` + `enriched_package.plays`

```python
envelope = result["analysis_envelope"]
all_plays = result["enriched_package"]["plays"]

# Get scoring drives from key moments
scoring_drives = [m for m in envelope["key_moments"] if "TD" in m["label"] or "FG" in m["label"]]

for drive in scoring_drives:
    print(f"\n{drive['label']}")
    
    # Get plays in this drive
    drive_play_ids = drive["plays"]
    drive_plays = [p for p in all_plays if p["play_id"] in drive_play_ids]
    
    # Calculate drive stats
    total_yards = sum(p["yards_gained"] for p in drive_plays)
    num_plays = len(drive_plays)
    
    print(f"  {num_plays} plays, {total_yards} yards")
    print(f"  Result: {drive['outcome']}")
```

### Use Case 4: Compare Teams

**Goal**: Side-by-side team comparison

**What to use**: `game_summaries.team_summaries`

```python
teams = result["game_summaries"]["team_summaries"]
team1_name = list(teams.keys())[0]
team2_name = list(teams.keys())[1]

team1 = teams[team1_name]
team2 = teams[team2_name]

comparison = f"""
{team1_name} vs {team2_name}

Total Yards:
  {team1_name}: {team1['total_yards']}
  {team2_name}: {team2['total_yards']}

Yards Per Play:
  {team1_name}: {team1['yards_per_play']:.1f}
  {team2_name}: {team2['yards_per_play']:.1f}

Touchdowns:
  {team1_name}: {team1['touchdowns']}
  {team2_name}: {team2['touchdowns']}

Turnovers:
  {team1_name}: {team1['turnovers']}
  {team2_name}: {team2['turnovers']}
"""
print(comparison)
```

## Integration Checklist

Use this checklist to integrate the Game Analysis API into your application:

### ☐ Phase 1: Setup & Configuration

- [ ] **1.1**: Save the API URL: `https://game-analysis-hjm4dt4a5q-uc.a.run.app`
- [ ] **1.2**: Choose your integration method:
  - [ ] Command-line (curl)
  - [ ] Python script
  - [ ] n8n workflow
  - [ ] Other tool/language
- [ ] **1.3**: Set up authentication if needed (currently none required)
- [ ] **1.4**: Prepare error handling for HTTP status codes (200, 400, 422, 500)

### ☐ Phase 2: Data Preparation

- [ ] **2.1**: Identify your data source (where you get play-by-play data)
- [ ] **2.2**: Map your data fields to the required format:
  - [ ] season → year as integer
  - [ ] week → week number as integer
  - [ ] game_id → format as "YYYY_WW_AWAY_HOME"
  - [ ] plays → array of play objects
- [ ] **2.3**: Create a sample request with test data
- [ ] **2.4**: Validate your JSON format (use a JSON validator tool)
- [ ] **2.5**: Decide on optional parameters:
  - [ ] fetch_data: true or false?
  - [ ] enable_envelope: true or false?
  - [ ] Custom correlation_id?

### ☐ Phase 3: Initial Testing

- [ ] **3.1**: Test with minimal data (1-3 plays) to verify connection
- [ ] **3.2**: Check response structure matches documentation
- [ ] **3.3**: Verify you can access all response sections:
  - [ ] game_info
  - [ ] game_summaries
  - [ ] analysis_envelope
  - [ ] enriched_package
- [ ] **3.4**: Test error scenarios:
  - [ ] Missing required field (should return 400)
  - [ ] Invalid game_id format (should return 422)
  - [ ] Malformed JSON (should return 400)
- [ ] **3.5**: Measure response times for your data volume

### ☐ Phase 4: Data Extraction

- [ ] **4.1**: Write code to extract team summaries
  - [ ] Parse team_summaries object
  - [ ] Extract key metrics (yards, touchdowns, etc.)
- [ ] **4.2**: Write code to extract player summaries
  - [ ] Parse player_summaries object
  - [ ] Handle position-specific stats
- [ ] **4.3**: Write code to extract analysis envelope
  - [ ] Parse game header
  - [ ] Parse team one-liners
  - [ ] Parse player quick refs
  - [ ] Parse key moments
- [ ] **4.4**: Write code to follow data links
  - [ ] Extract data_links section
  - [ ] Navigate to enriched_package.plays
  - [ ] Navigate to enriched_package.player_data
- [ ] **4.5**: Test with full game data (100+ plays)

### ☐ Phase 5: Data Processing

- [ ] **5.1**: Decide what to do with the data:
  - [ ] Store in database?
  - [ ] Send to AI for analysis?
  - [ ] Display in UI?
  - [ ] Export to file?
- [ ] **5.2**: Implement your data processing logic
- [ ] **5.3**: Handle validation warnings appropriately
- [ ] **5.4**: Implement correlation ID tracking (for debugging)
- [ ] **5.5**: Add logging for successful requests

### ☐ Phase 6: Error Handling

- [ ] **6.1**: Implement retry logic for network errors
- [ ] **6.2**: Handle validation errors (422 responses)
  - [ ] Parse error message
  - [ ] Fix data format
  - [ ] Retry request
- [ ] **6.3**: Handle server errors (500 responses)
  - [ ] Log error details
  - [ ] Wait and retry
  - [ ] Alert administrators if persistent
- [ ] **6.4**: Handle partial success scenarios
  - [ ] Check status field in response
  - [ ] Process available data even if status is "partial"
- [ ] **6.5**: Implement timeout handling (set max wait time)

### ☐ Phase 7: Performance Optimization

- [ ] **7.1**: Decide on fetch_data strategy:
  - [ ] false = Faster, uses only your input data
  - [ ] true = Slower, fetches additional data from database
- [ ] **7.2**: Decide on envelope_enabled strategy:
  - [ ] true = Get both envelope and full data
  - [ ] false = Get only full data (smaller response)
- [ ] **7.3**: Implement response caching if needed
- [ ] **7.4**: Batch requests if processing multiple games
- [ ] **7.5**: Monitor response times and adjust as needed

### ☐ Phase 8: Integration with Downstream Systems

- [ ] **8.1**: If using AI/LLM:
  - [ ] Format envelope data for AI prompt
  - [ ] Test AI analysis with real envelopes
  - [ ] Refine prompt based on results
- [ ] **8.2**: If storing in database:
  - [ ] Design database schema for summaries
  - [ ] Design schema for enriched package
  - [ ] Implement data insertion logic
  - [ ] Handle updates for existing games
- [ ] **8.3**: If using in n8n:
  - [ ] Create workflow with HTTP Request node
  - [ ] Add data transformation nodes
  - [ ] Connect to next workflow steps
  - [ ] Test end-to-end workflow
- [ ] **8.4**: Document your integration for team members

### ☐ Phase 9: Production Readiness

- [ ] **9.1**: Test with production data volume
- [ ] **9.2**: Set up monitoring and alerting
  - [ ] Monitor API availability
  - [ ] Monitor response times
  - [ ] Alert on errors
- [ ] **9.3**: Document API usage for your team
- [ ] **9.4**: Create runbooks for common issues
- [ ] **9.5**: Train team members on using the API

### ☐ Phase 10: Ongoing Maintenance

- [ ] **10.1**: Monitor API usage patterns
- [ ] **10.2**: Review and act on validation warnings
- [ ] **10.3**: Update integration if API changes
- [ ] **10.4**: Optimize based on real-world performance
- [ ] **10.5**: Collect user feedback and iterate

## Troubleshooting Guide

### Problem: Getting 400 Bad Request

**Cause**: Invalid JSON or missing required fields

**Solution**:
1. Validate your JSON using a tool like jsonlint.com
2. Check that all required fields are present:
   - schema_version
   - producer
   - game_package.season
   - game_package.week
   - game_package.game_id
   - game_package.plays (with at least 1 play)
3. Ensure field types are correct (integers for numbers, strings for text)

### Problem: Getting 422 Validation Failed

**Cause**: JSON is valid but data doesn't pass validation

**Solution**:
1. Read the error message in the response
2. Common issues:
   - game_id format incorrect (should be "YYYY_WW_AWAY_HOME")
   - season not a valid year
   - plays array is empty
   - play objects missing required fields
3. Fix the identified issue and retry

### Problem: Getting 500 Internal Server Error

**Cause**: Unexpected error on the server

**Solution**:
1. Wait a few seconds and retry
2. If persistent, check:
   - Is your data extremely large? (>1000 plays)
   - Are there unusual characters in player IDs?
3. Contact support if error continues

### Problem: Response is Very Large

**Cause**: Enriched package includes all play details

**Solution**:
1. Set `enable_envelope: false` if you only need summaries
2. Set `fetch_data: false` to avoid fetching additional data
3. Process the response in chunks rather than all at once
4. Only request the data you actually need

### Problem: Can't Find Specific Player Data

**Cause**: Player wasn't selected as "relevant" for detailed analysis

**Solution**:
1. Check `processing.players_selected` count in response
2. The API selects top 10-25 players based on impact
3. Check `game_summaries.player_summaries` - all selected players are there
4. For all players (not just selected): enable `fetch_data: true`

### Problem: Missing Play Details

**Cause**: Input data didn't include those fields

**Solution**:
1. Check validation warnings in response
2. Warnings will list which fields are missing:
   - "3 plays missing quarter information"
   - "5 plays missing down information"
3. These don't prevent processing but reduce data richness
4. Improve your input data if possible

### Problem: Correlation ID Not Appearing

**Cause**: Not extracting it from the response correctly

**Solution**:
1. It's always in the response at the top level
2. Access it as: `response["correlation_id"]`
3. Format is: `{game_id}-{timestamp}-{uuid}`
4. Use it for tracking and debugging

## Best Practices

### 1. Always Check Status First
```python
response = call_api(request_data)
if response["status"] == "success":
    # Process data
    process_summaries(response)
elif response["status"] == "partial":
    # Some data missing but continue
    log_warning("Partial data received")
    process_summaries(response)
else:
    # Failed
    log_error("Analysis failed")
    handle_failure(response)
```

### 2. Use Correlation IDs for Debugging
```python
correlation_id = response["correlation_id"]
logger.info(f"Processing game with correlation ID: {correlation_id}")

# Later if there's an issue:
logger.error(f"Error in processing [correlation_id={correlation_id}]")
```

### 3. Handle Validation Warnings
```python
warnings = response["validation"]["warnings"]
if warnings:
    for warning in warnings:
        logger.warning(f"Data quality issue: {warning}")
    # Decide if you want to continue or fix data first
```

### 4. Start with Small Data
```python
# Test with minimal game first
test_request = {
    "schema_version": "1.0.0",
    "producer": "my-app-test",
    "fetch_data": False,  # Faster for testing
    "enable_envelope": True,
    "game_package": {
        "season": 2025,
        "week": 1,
        "game_id": "2025_01_KC_BAL",
        "plays": [...] # Just 3-5 plays for testing
    }
}

# Once working, use full game data
```

### 5. Cache Responses When Appropriate
```python
import json
from datetime import datetime, timedelta

cache = {}

def get_game_analysis(game_id):
    # Check cache first
    if game_id in cache:
        cached_data, cached_time = cache[game_id]
        if datetime.now() - cached_time < timedelta(hours=1):
            return cached_data
    
    # Not in cache or expired, fetch fresh
    response = call_api(game_id)
    cache[game_id] = (response, datetime.now())
    return response
```

### 6. Use the Right Output for Your Use Case

| Use Case | What to Use | Why |
|----------|-------------|-----|
| AI Analysis | `analysis_envelope` | Compact, optimized for LLMs |
| Statistical Report | `game_summaries` | Pre-calculated metrics |
| Play-by-Play Review | `enriched_package.plays` | Complete detail |
| Player Deep Dive | `enriched_package.player_data` | Full player stats |
| Quick Overview | `analysis_envelope.teams` + `key_moments` | Fast summary |

### 7. Build Progressive Disclosure

Show summary first, details on demand:
```python
# First, show the envelope
envelope = response["analysis_envelope"]
show_game_header(envelope["game"])
show_team_summaries(envelope["teams"])
show_key_moments(envelope["key_moments"])

# User clicks "Show Details"
def on_show_details():
    # Now load full data
    enriched = response["enriched_package"]
    show_all_plays(enriched["plays"])
    show_player_details(enriched["player_data"])
```

## Support and Resources

### Documentation
- **Technical Guide**: `COMPREHENSIVE_GUIDE.md` - Deep technical details
- **Deployment Guide**: `DEPLOYMENT.md` - Cloud Function deployment
- **README**: Module overview and quick start

### Testing
- **Test Endpoint**: Use the same URL for testing
- **Sample Data**: `test_requests/http_api_test_minimal.json`
- **Local Testing**: Available for development

### Monitoring
- **Cloud Console**: View logs and metrics
- **Correlation IDs**: Track requests through the system
- **Status Endpoint**: Check if API is operational

### Getting Help
1. Check validation warnings in responses
2. Review error messages for specific guidance
3. Check monitoring logs for your correlation ID
4. Contact development team with correlation ID and error details

## Conclusion

The Game Analysis API transforms complex NFL game data into organized, actionable insights. By following this guide and using the integration checklist, you can successfully integrate the API into your workflows and applications.

**Key Takeaways**:
- Start with small test data to verify your integration
- Use the analysis envelope for AI/quick summaries
- Follow data links to access detailed information
- Handle errors gracefully with retry logic
- Monitor using correlation IDs
- Cache responses when appropriate

The API is production-ready, actively monitored, and designed for reliable operation. Happy analyzing!
