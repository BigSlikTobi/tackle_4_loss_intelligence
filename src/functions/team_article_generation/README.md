# Team Article Generation Module

A production-ready AI-powered article generation service that synthesizes multiple article summaries into cohesive, comprehensive daily team update articles using OpenAI GPT-4/GPT-5. This module follows function-based isolation principles and supports both library and Cloud Function deployment.

## Features

- **Multi-Summary Synthesis**: Combines multiple article summaries into one coherent narrative
- **AI-Powered Writing**: Uses OpenAI GPT-4o or GPT-5 with flex-mode pricing
- **Narrative Analysis**: Automatically detects central themes across summaries
- **Structured Output**: JSON schema enforcement for consistent article structure
- **Article Validation**: Ensures completeness and factual alignment with sources
- **Flexible Prompting**: Configurable tone, style, and narrative focus
- **Retry Logic**: Handles API failures gracefully
- **Metrics Collection**: Tracks token usage and processing time

## Installation

```bash
cd src/functions/team_article_generation
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Configure via the central project `.env` file:

```bash
# Required
OPENAI_API_KEY="your-openai-api-key-here"

# Optional
OPENAI_TEAM_MODEL="gpt-4o"  # Options: gpt-4o, gpt-4-turbo, gpt-3.5-turbo
LOG_LEVEL=INFO
```

See `.env.example` at project root for complete configuration template.

## Usage

### Command Line Interface

Generate an article from multiple summaries:

```bash
cd scripts
python generate_article_cli.py summaries.json \
  --team-name "Kansas City Chiefs" \
  --team-abbr "KC"
```

With options:

```bash
# Verbose output with debug logging
python generate_article_cli.py summaries.json --team-name "Chiefs" --team-abbr "KC" --verbose

# Custom model
python generate_article_cli.py summaries.json --team-name "Chiefs" --team-abbr "KC" --model gpt-4-turbo

# Custom temperature (0.0-1.0, default 0.7)
python generate_article_cli.py summaries.json --team-name "Chiefs" --team-abbr "KC" --temperature 0.5

# Save to file
python generate_article_cli.py summaries.json --team-name "Chiefs" --team-abbr "KC" --output article.json

# Pretty-print JSON
python generate_article_cli.py summaries.json --team-name "Chiefs" --team-abbr "KC" --pretty
```

Input format (summaries.json):

```json
{
  "team_name": "Kansas City Chiefs",
  "team_abbr": "KC",
  "summaries": [
    "Patrick Mahomes returned to practice this week...",
    "The Chiefs defense ranked first in the AFC...",
    "Travis Kelce reached a milestone with his 100th..."
  ]
}
```

### Python API

```python
from src.functions.team_article_generation.core.llm.openai_client import OpenAIGenerationClient
from src.functions.team_article_generation.core.contracts.team_article import SummaryBundle

# Create client
client = OpenAIGenerationClient(model="gpt-4o")

# Create bundle
bundle = SummaryBundle(
    team_name="Kansas City Chiefs",
    team_abbr="KC",
    summaries=[
        "Patrick Mahomes returned to practice...",
        "The Chiefs defense ranked first...",
        "Travis Kelce reached a milestone..."
    ]
)

# Generate article
article = client.generate(bundle)

# Check for errors
if article.error:
    print(f"Generation failed: {article.error}")
else:
    print(f"Headline: {article.headline}")
    print(f"Sub-header: {article.sub_header}")
    print(f"Intro: {article.introduction_paragraph}")
    print(f"Content paragraphs: {len(article.content)}")
```

With custom options:

```python
from src.functions.team_article_generation.core.contracts.team_article import GenerationOptions

options = GenerationOptions(
    model="gpt-4-turbo",
    temperature=0.5,
    max_output_tokens=1500,
    service_tier="flex",
    request_timeout_seconds=60
)

article = client.generate(bundle, options=options)
```

### Cloud Function Deployment

Deploy to Google Cloud Functions:

```bash
cd functions
./deploy.sh
```

Run locally for testing:

```bash
cd functions
./run_local.sh
```

HTTP API usage:

```bash
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{
    "team_name": "Kansas City Chiefs",
    "team_abbr": "KC",
    "summaries": [
      "Summary 1...",
      "Summary 2...",
      "Summary 3..."
    ]
  }'
```

## Architecture

### Article Generation Pipeline

```
1. Receive Summary Bundle
   ↓
2. Analyze Central Narrative
   ↓
3. Build Structured Prompt
   ↓
4. Call OpenAI API (with JSON schema)
   ↓
5. Extract & Parse Response
   ↓
6. Validate Article Structure
   ↓
7. Return Generated Article
```

### Narrative Analysis

The module automatically detects central themes across summaries:

- **Injury updates**: When multiple summaries mention player health
- **Performance trends**: When stats and rankings are prominent
- **Game preparation**: When practice and strategy dominate
- **Personnel changes**: When roster moves are the focus

This informs the prompt to create a cohesive narrative arc.

### JSON Schema Enforcement

Uses OpenAI's structured output feature to guarantee consistent format:

```json
{
  "type": "object",
  "properties": {
    "headline": {"type": "string"},
    "sub_header": {"type": "string"},
    "introduction_paragraph": {"type": "string"},
    "content": {
      "type": "array",
      "items": {"type": "string"},
      "minItems": 2
    }
  },
  "required": ["headline", "sub_header", "introduction_paragraph", "content"]
}
```

## Data Models

```python
@dataclass
class SummaryBundle:
    team_name: str
    team_abbr: str
    summaries: List[str]            # List of article summaries
    metadata: Dict[str, Any]        # Additional context

@dataclass
class GeneratedArticle:
    headline: str                   # Main headline
    sub_header: str                 # Supporting headline
    introduction_paragraph: str     # Opening paragraph
    content: List[str]              # Body paragraphs (2+)
    central_theme: Optional[str]    # Detected narrative theme
    word_count: int
    tokens_used: int
    processing_time_ms: int
    error: Optional[str]

@dataclass
class GenerationOptions:
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_output_tokens: int = 1500
    service_tier: str = "flex"      # OpenAI flex pricing
    request_timeout_seconds: int = 240
```

## Project Structure

```
team_article_generation/
├── core/
│   ├── contracts/
│   │   └── team_article.py           # Data models
│   ├── llm/
│   │   ├── openai_client.py          # OpenAI API client
│   │   └── prompts.py               # Prompt templates and builders
│   └── processors/
│       ├── narrative_analyzer.py     # Theme detection
│       └── article_validator.py      # Output validation
├── scripts/
│   └── generate_article_cli.py       # Command-line tool
├── functions/
│   ├── main.py                       # Cloud Function entry
│   ├── local_server.py               # Local testing server
│   ├── deploy.sh                     # Deployment script
│   └── run_local.sh                  # Local execution
├── requirements.txt                  # Dependencies
└── README.md                         # This file
```

## Dependencies

- **openai**: OpenAI API client
- **pydantic**: Data validation and JSON schema

See `requirements.txt` for complete list with versions.

## Prompt Engineering

The article generation prompt is optimized for:

1. **Narrative Coherence**: Creates a single story from multiple sources
2. **Team Focus**: Maintains consistent perspective about the team
3. **Fact Preservation**: Never invents information
4. **Professional Tone**: Writes like an experienced beat reporter
5. **Structural Clarity**: Follows journalistic article structure

Example prompt structure:

```
You are an experienced NFL beat writer crafting a daily update article.
Use only the provided summaries, avoid speculation, and ensure the piece reads like a cohesive story.
Write in third person about the Kansas City Chiefs.

Central Theme: Team prepares for upcoming game with key players returning from injury

Summaries:
1. Patrick Mahomes returned to practice this week...
2. The Chiefs defense ranked first in the AFC...
3. Travis Kelce reached a milestone with his 100th...

Create an article with:
- A compelling headline
- A sub-header providing context
- An introduction paragraph that sets up the story
- 2-4 content paragraphs that develop the narrative
```

## Article Validation

The module validates generated articles for:

- **Required fields**: All fields present (headline, sub_header, intro, content)
- **Content length**: At least 2 content paragraphs
- **Fact checking**: All claims traceable to source summaries
- **No hallucinations**: No invented statistics or quotes
- **Structural integrity**: Proper paragraph flow

## Performance

Typical performance metrics:

- **Processing time**: 10-30s per article
- **Token usage**: 500-1500 tokens (input + output)
- **Cost**: $0.02-0.06 per article with GPT-4o
- **Quality**: High coherence and factual accuracy

Optimization tips:

- Use `gpt-4o` for best balance of speed, cost, and quality
- Batch API calls when generating multiple team articles
- Cache generated articles to avoid redundant API calls
- Pre-filter summaries to most relevant content

## Error Handling

Graceful error handling with fallbacks:

- **API failures**: Return article with error field set
- **Invalid JSON**: Retry or fall back to heuristic article
- **Schema violations**: Validate and fix structure
- **Timeout**: Configurable timeout with clear error message

Example:

```python
article = client.generate(bundle)
if article.error:
    if "timeout" in article.error.lower():
        print("Generation timed out - retry with longer timeout")
    else:
        print(f"Generation failed: {article.error}")
```

## Testing

Manual testing with CLI:

```bash
# Create test summaries
cat > test_summaries.json << EOF
{
  "team_name": "Kansas City Chiefs",
  "team_abbr": "KC",
  "summaries": [
    "Patrick Mahomes threw for 300 yards in practice.",
    "The defense allowed zero touchdowns this week.",
    "Travis Kelce is on track for a record season."
  ]
}
EOF

# Generate article
python scripts/generate_article_cli.py test_summaries.json --verbose
```

## Troubleshooting

**API key not found:**
```bash
export OPENAI_API_KEY="your-key-here"
# Or add to .env file
```

**Generation timeout:**
- Increase timeout: `--request-timeout 300`
- Check OpenAI API status
- Verify network connectivity

**Invalid JSON response:**
- Module automatically retries
- Falls back to heuristic article if all retries fail
- Check OpenAI model supports JSON schema

**Import errors:**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Integration with Daily Team Update Pipeline

This module is used by the daily_team_update pipeline for step 4 (article generation):

```python
from src.functions.team_article_generation.core.llm.openai_client import OpenAIGenerationClient
from src.functions.team_article_generation.core.contracts.team_article import SummaryBundle

client = OpenAIGenerationClient()

bundle = SummaryBundle(
    team_name=team.name,
    team_abbr=team.abbreviation,
    summaries=[s.content for s in summaries]
)

article = client.generate(bundle)
# Pass to translation...
```

## Function Isolation

This module follows the platform's function-based isolation principles:

- ✅ **Complete Independence**: Can be deleted without affecting other modules
- ✅ **Isolated Dependencies**: Own `requirements.txt` and virtualenv
- ✅ **Separate Deployment**: Deploys independently to Cloud Functions
- ✅ **Minimal Shared Code**: Only uses generic utilities from `src/shared/`

No imports from other function modules.
